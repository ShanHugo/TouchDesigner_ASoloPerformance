"""
Script TOP Callbacks - card_visual/kintsugiDraw1

Act 3 kintsugi payoff. Brings back the exact crack this visitor made in
Act 2 (a snapshot of crackDraw1's persisted segments, not a new random
one), shows it as a cold pale scar once the card locks into its slot, then
fills it with gold flowing outward from the impact point while the visitor
holds the self-embrace. The wound is not erased - it is mended with gold.

Rendered centered on the canvas; kintsugiFollow1 (transformTOP) moves it
onto the chest, so per-frame work here is numpy-only. The line mask is
drawn with PIL once per snapshot (4x supersampled, then downsampled).

The gold front is radial distance from the impact point. The crack spokes
are radial, so this reads as gold travelling along each spoke and filling
each concentric ring as it reaches it.

Timeline:
  card light lands      -> scar surfaces outward from the landing point (act3PhaseState1)
  hug held (confirming) -> gold advances, capped at Prelatchfront
  embraced latches      -> gold keeps flowing until fully filled
  embrace auto-reset    -> gold clears (scar stays while card is locked)
  card unlocked/reset   -> everything clears
"""

import math
import random
import numpy as np
from PIL import Image, ImageDraw

CRACK_DAT_PATH = '/project1/care_second_state/feeding_visual/crackDraw1_callbacks'
CARDLOCK_PATH = '/project1/care_third_state/card_sense/cardLockState1'
EMBRACE_PATH = '/project1/care_third_state/embrace_sense/embraceState1'
PHASE_PATH = '/project1/care_third_state/card_sense/act3PhaseState1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (2,)  # Act 3 only
SRC_W, SRC_H = 1280.0, 720.0  # canvas crackDraw1's segments were drawn on
SUPERSAMPLE = 4

SCAR_RGB = (0.62, 0.68, 0.78)
GOLD_RGB = (1.0, 0.70, 0.26)
EDGE_RGB = (1.25, 1.02, 0.62)

_state = {
	'segments': None,   # snapshot: (dx0, dy0, dx1, dy1, width) as frame fractions from the impact point
	'speckles': None,   # (dx, dy, radius) frame fractions
	'max_r': 1.0,
	'from_visitor': False,
	'line': None,       # (h, w) float32 0..1 line coverage, PIL orientation
	'dist': None,       # (h, w) float32 radial distance / max_r
	'key': None,        # (w, h, scale, widthmul) the cached masks belong to
	'reveal': 0.0,
	'front': 0.0,
	'prev_locked': False,
	'prev_embraced': False,
	'last_time': None,
	'blank': None,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Kintsugi')

	def addf(name, label, default, lo, hi):
		p = page.appendFloat(name, label=label)
		p[0].default = default
		p[0].val = default
		p[0].normMin = lo
		p[0].normMax = hi

	addf('Patternscale', 'Crack Size On Chest', 0.45, 0.1, 1.0)
	addf('Linewidthmul', 'Line Width Multiplier', 1.0, 0.3, 3.0)
	addf('Revealseconds', 'Scar Surfacing After Card Light Lands (s)', 2.5, 0.2, 10.0)
	addf('Prelatchfront', 'Gold Reach While Hug Is Confirming (0-1)', 0.35, 0.0, 1.0)
	addf('Goldfillseconds', 'Gold Full Fill Duration (s)', 5.0, 0.5, 20.0)
	addf('Goldsoftness', 'Gold Front Softness', 0.12, 0.02, 0.5)
	addf('Scaralpha', 'Scar Brightness', 0.55, 0.0, 1.0)
	addf('Goldintensity', 'Gold Brightness', 1.4, 0.2, 3.0)
	addf('Chestyoffset', 'Vertical Offset From Chest (fraction)', 0.0, -0.3, 0.3)
	# keep the whole crack on screen when the visitor stands close and their chest
	# drops out of frame (the scar's half-extent at Patternscale 0.45 is ~0.12 x / ~0.18 y)
	addf('Edgemarginx', 'Keep Crack Centre This Far From Left/Right Edge', 0.15, 0.0, 0.5)
	addf('Edgemarginy', 'Keep Crack Centre This Far From Top/Bottom Edge', 0.2, 0.0, 0.5)
	p = page.appendToggle('Mirrorchestx', label='Mirror Chest X')
	p[0].default = False
	p[0].val = False
	page.appendPulse('Resetkintsugi', label='Reset Kintsugi')
	return


def onPulse(par):
	if par.name == 'Resetkintsugi':
		_reset(clear_snapshot=True)
	return


def _reset(clear_snapshot):
	_state['reveal'] = 0.0
	_state['front'] = 0.0
	if clear_snapshot:
		_state['segments'] = None
		_state['speckles'] = None
		_state['line'] = None
		_state['dist'] = None
		_state['key'] = None


def _synthetic_pattern():
	"""Fallback when Act 2 never produced a crack (e.g. Act 3 tested on its
	own): same spokes-plus-rings structure as crackDraw1, fixed seed so it is
	identical every run. x offsets are squeezed by SRC_H/SRC_W to match how a
	real 1280x720 crack lands in frame fractions."""
	rng = random.Random(7)
	aspect = SRC_H / SRC_W
	n = 7
	base = rng.uniform(0, 360)
	angles = [base + i * 360.0 / n + rng.uniform(-12, 12) for i in range(n)]
	tips = [(0.0, 0.0)] * n
	step = 0.07
	segs = []
	for ring in range(3):
		new_tips = []
		for i in range(n):
			x, y = tips[i]
			a = angles[i]
			for _ in range(3 if ring == 0 else 2):
				a += rng.uniform(-12, 12)
				ln = step * rng.uniform(0.85, 1.15)
				nx = x + math.cos(math.radians(a)) * ln * aspect
				ny = y + math.sin(math.radians(a)) * ln
				segs.append((x, y, nx, ny, 0.016 - 0.003 * ring))
				x, y = nx, ny
			angles[i] = a
			new_tips.append((x, y))
		if ring < 2:
			for i in range(n):
				x0, y0 = new_tips[i]
				x1, y1 = new_tips[(i + 1) % n]
				mx = (x0 + x1) / 2.0 + rng.uniform(-0.012, 0.012) * aspect
				my = (y0 + y1) / 2.0 + rng.uniform(-0.012, 0.012)
				segs.append((x0, y0, mx, my, 0.009))
				segs.append((mx, my, x1, y1, 0.009))
		tips = new_tips
	return segs, []


def _snapshot():
	segs_px, specks_px, origin = [], [], None
	try:
		src = op(CRACK_DAT_PATH).module._state
		segs_px = list(src['segments'])
		specks_px = list(src['speckles'])
		origin = src['origin']
	except Exception:
		pass

	if segs_px and origin is not None:
		ox, oy = origin
		segs = [((x0 - ox) / SRC_W, (y0 - oy) / SRC_H, (x1 - ox) / SRC_W, (y1 - oy) / SRC_H, w / SRC_H)
		        for (x0, y0, x1, y1, w) in segs_px]
		specks = [((x - ox) / SRC_W, (y - oy) / SRC_H, r / SRC_H) for (x, y, r) in specks_px]
		_state['from_visitor'] = True
	else:
		segs, specks = _synthetic_pattern()
		_state['from_visitor'] = False

	max_r = 1e-6
	for (a, b, c, d, _w) in segs:
		max_r = max(max_r, math.hypot(a, b), math.hypot(c, d))
	_state['segments'] = segs
	_state['speckles'] = specks
	_state['max_r'] = max_r
	_state['key'] = None


def _build_masks(w, h, scale, widthmul, key):
	W, H = w * SUPERSAMPLE, h * SUPERSAMPLE
	img = Image.new('L', (W, H), 0)
	dr = ImageDraw.Draw(img)
	cx, cy = W / 2.0, H / 2.0
	for (dx0, dy0, dx1, dy1, wf) in _state['segments']:
		lw = max(1.0, wf * H * scale * widthmul)
		p0 = (cx + dx0 * scale * W, cy + dy0 * scale * H)
		p1 = (cx + dx1 * scale * W, cy + dy1 * scale * H)
		dr.line([p0, p1], fill=255, width=int(round(lw)))
		r = lw / 2.0
		for (x, y) in (p0, p1):  # round joints so spokes don't show gaps
			dr.ellipse([x - r, y - r, x + r, y + r], fill=255)
	for (dx, dy, rf) in _state['speckles']:
		r = max(1.0, rf * H * scale * widthmul)
		x, y = cx + dx * scale * W, cy + dy * scale * H
		dr.ellipse([x - r, y - r, x + r, y + r], fill=255)

	rs = getattr(Image, 'Resampling', Image)
	small = img.resize((w, h), rs.LANCZOS)
	_state['line'] = np.asarray(small, dtype=np.float32) / 255.0

	ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
	dxf = (xs + 0.5 - w / 2.0) / (w * scale)
	dyf = (ys + 0.5 - h / 2.0) / (h * scale)
	_state['dist'] = (np.sqrt(dxf * dxf + dyf * dyf) / _state['max_r']).astype(np.float32)
	_state['key'] = key


def _blank(scriptOp, w, h):
	# full resolution, not 4x4 - a tiny output would drag the downstream
	# composite chain's resolution down with it
	if _state['blank'] is None or _state['blank'].shape != (h, w, 4):
		_state['blank'] = np.zeros((h, w, 4), dtype=np.float32)
	scriptOp.copyNumpyArray(_state['blank'])


def onCook(scriptOp):
	# Step 4 replaced Act 3's kintsugi picture with the candle, so nothing displays
	# this any more - it was still rendering with PIL every frame (up to ~59 ms on a
	# snapshot frame). Skip the work while the candle is on; flip Uses3candle off and
	# this comes back exactly as before.
	ec = op('/project1/effect_controller')
	if ec is not None and ec.par.Uses3candle.eval():
		return
	w = int(scriptOp.par.resolutionw.eval())
	h = int(scriptOp.par.resolutionh.eval())
	now = absTime.seconds

	sw = op(SWITCH_PATH)
	if not (sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES):
		_state['last_time'] = None
		_blank(scriptOp, w, h)
		return

	dt = 0.0 if _state['last_time'] is None else min(0.25, max(0.0, now - _state['last_time']))
	_state['last_time'] = now

	locked, landed, embraced, held, hold_needed = False, False, False, 0.0, 2.0
	try:
		cl = op(CARDLOCK_PATH)
		locked = cl is not None and cl['locked'].eval() > 0.5
		ph = op(PHASE_PATH)
		landed = ph is not None and ph['landed'].eval() > 0.5
		em = op(EMBRACE_PATH)
		if em is not None:
			embraced = em['embraced'].eval() > 0.5
			held = em['held_seconds'].eval()
			hold_needed = max(0.1, em.par.Holdseconds.eval())
	except Exception as e:
		scriptOp.store('last_error', str(e))

	if locked and not _state['prev_locked']:
		_snapshot()
	if _state['prev_locked'] and not locked:
		_reset(clear_snapshot=False)
	if _state['prev_embraced'] and not embraced:
		_state['front'] = 0.0  # embrace auto-reset (installation loop) clears the gold
	_state['prev_locked'] = locked
	_state['prev_embraced'] = embraced
	if locked and _state['segments'] is None:
		_snapshot()  # script reloaded while the card was already locked

	par = scriptOp.par
	rsec = max(0.05, par.Revealseconds.eval())
	if locked and landed:
		_state['reveal'] = min(1.0, _state['reveal'] + dt / rsec)
	else:
		_state['reveal'] = max(0.0, _state['reveal'] - dt / 0.6)

	if embraced:
		target_front = 1.0
	elif locked and landed:
		target_front = min(1.0, held / hold_needed) * par.Prelatchfront.eval()
	else:
		target_front = 0.0
	if target_front > _state['front']:
		# one-way: letting go of the hug early keeps the gold that already flowed in
		_state['front'] = min(target_front, _state['front'] + dt / max(0.1, par.Goldfillseconds.eval()))

	reveal = _state['reveal']
	if _state['segments'] is None or reveal <= 0.0:
		_blank(scriptOp, w, h)
		return

	scale = par.Patternscale.eval()
	widthmul = par.Linewidthmul.eval()
	key = (w, h, round(scale, 4), round(widthmul, 4))
	if _state['key'] != key:
		_build_masks(w, h, scale, widthmul, key)

	line = _state['line']
	dist = _state['dist']
	front = _state['front']
	soft = max(0.01, par.Goldsoftness.eval())
	reach = front * (1.0 + soft)  # at front=1 even the outermost tips are fully gold
	gold = np.clip((reach - dist) / soft, 0.0, 1.0)
	done = front >= 0.999
	gi = par.Goldintensity.eval() * (1.0 + (0.12 * math.sin(now * 1.6) if done else 0.0))

	# the scar surfaces outward from where the card light landed, not all at once
	rsoft = 0.25
	rv = np.clip((reveal * (1.0 + rsoft) - dist) / rsoft, 0.0, 1.0)
	scar_a = par.Scaralpha.eval() * rv * (1.0 - gold)
	gold_a = gold * rv
	r = scar_a * SCAR_RGB[0] + gold_a * GOLD_RGB[0] * gi
	g = scar_a * SCAR_RGB[1] + gold_a * GOLD_RGB[1] * gi
	b = scar_a * SCAR_RGB[2] + gold_a * GOLD_RGB[2] * gi
	a = np.maximum(scar_a, gold_a)

	if front > 0.0 and not done:
		# bright molten leading edge where the gold is currently arriving
		edge = np.exp(-((dist - reach) / (soft * 0.6)) ** 2) * rv
		r = r + edge * EDGE_RGB[0] * gi
		g = g + edge * EDGE_RGB[1] * gi
		b = b + edge * EDGE_RGB[2] * gi
		a = np.maximum(a, edge)

	out = np.stack([r * line, g * line, b * line, np.clip(a, 0.0, 1.0) * line], axis=2)
	scriptOp.copyNumpyArray(np.ascontiguousarray(np.flipud(out), dtype=np.float32))  # PIL row0=top -> TD row0=bottom
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
