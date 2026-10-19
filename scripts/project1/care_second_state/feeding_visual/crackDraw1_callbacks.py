"""
Script TOP Callbacks - feeding_visual/crackDraw1

Draws the accumulating crack pattern as a classic "impact fracture" -
radial cracks spreading straight-ish out from the mouth position, with a
jagged ring crack connecting the radial tips every time it spreads further
(and occasionally a new radial crack splitting a gap on a later hit).
This matches how glass/ceramic actually fractures under repeated impact,
unlike the earlier version's fully-random branch-from-anywhere growth.

Per client direction: the crack behaves like repeatedly striking the same
spot on a pane of glass - it does NOT reset and redraw independently each
time. The first hit seeds the radial spokes; every hit after that extends
them outward and rings them, so the whole fracture network gets bigger
the more times you feed. The crack also does not fade away to nothing -
once part of it exists it stays visible permanently (PERSISTENT_ALPHA
floor), with each fresh hit adding a brief overbright flash that eases
back down to that permanent level. Once the crack has spread
HEAL_AFTER_HITS times, pressing the clouds down (weary_effective easing
toward 0) also fades the crack, in step with the clouds clearing.

The line-art mask is only re-rendered with PIL when a hit actually adds
new growth (cheap to redraw once per event) - every other frame just
cheaply rescales the cached mask by the current recoil/flash values.

me - this OP
scriptOp - the OP which is cooking
"""

import random
import math
import numpy as np
from PIL import Image, ImageDraw

RECOIL_PATH = '/project1/care_second_state/feeding_state/wearinessState1'
MOUTH_PATH = '/project1/care_second_state/feeding_visual/selectMouthPos2'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (1,)  # Act 2 only
FLASH_DUR = 0.2
PERSISTENT_ALPHA = 0.55   # crack's base scar brightness once it exists
MAX_SEGMENTS = 500        # cap total complexity across a long session
WEARY_PATH = '/project1/care_second_state/feeding_state/wearinessState1'
FEED_PATH = '/project1/care_second_state/feeding_state/feedingState1'
# Growth follows the feed COUNT, one step per feed, catching up if the count
# jumps (e.g. Unity reports a feed TD's camera missed, or OSC packets were
# lost). It used to fire on the rising edge of 'recoil', which collapsed a
# jump of 2+ into a single step. Read from storage, not the channel -
# feedingState1 is in a cook loop with wearinessState1 (see that node).
HEAL_AFTER_HITS = 3        # only once the crack has spread this many times does
                            # pressing the clouds down also fade the crack

_state = {
	'was_active': False,
	'prev_recoil_active': False,
	'segments': [],       # persistent, accumulates across hits: (x0,y0,x1,y1,width) px
	'speckles': [],        # persistent: (x,y,radius) px
	'origin': None,         # (x,y) px - where the first hit seeded the spokes
	'radial_angles': [],    # degrees, one per radial crack, drifts slightly as it extends
	'radial_tips': [],      # (x,y) px, current outer end of each radial crack
	'mask': None,           # cached rendered line-art, (h,w) float32 0..1
	'flash_start': None,
	'hit_count': 0,          # how many times the crack has spread (seed or grow)
	'entry_frame': False,
}


def _walk_radial(x, y, angle, num_seg, seg_len_px, width_px, segments, speckles):
	"""Walks outward from (x,y) at roughly `angle`, with only a small wander
	per step (unlike a free branch) so it reads as a straight-ish spoke
	radiating from the impact point, not a wandering tree branch."""
	for i in range(num_seg):
		angle += random.uniform(-13, 13)
		this_len = seg_len_px * random.uniform(0.82, 1.18)
		rad = math.radians(angle)
		nx = x + math.cos(rad) * this_len
		ny = y + math.sin(rad) * this_len
		this_width = max(1.0, width_px * (1.0 - i / max(1, num_seg) * 0.45))
		segments.append((x, y, nx, ny, this_width))
		if random.random() < 0.55:
			t = random.uniform(0.15, 0.85)
			sx = x + (nx - x) * t + random.uniform(-3, 3)
			sy = y + (ny - y) * t + random.uniform(-3, 3)
			speckles.append((sx, sy, random.uniform(1.3, 2.8)))
		x, y = nx, ny
	return x, y, angle


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Crack')
	p = page.appendFloat('Linewidthmul', label='Crack Line Width')
	p[0].default = 0.5; p[0].val = 0.5; p[0].normMin = 0.1; p[0].normMax = 2.0
	p = page.appendToggle('Keepbottomclear', label='No Cracks From The Bottom Edge (corners still allowed)')
	p[0].default = True; p[0].val = True
	p = page.appendMenu('Crackstyle', label='Crack Style')
	p[0].menuNames = ['branch', 'web']
	p[0].menuLabels = ['Branching (no rings)', 'Web (radial + rings)']
	p[0].default = 'branch'; p[0].val = 'branch'
	p = page.appendFloat('Cornerfrac', label='How Much Of The Bottom Counts As Corner')
	p[0].default = 0.2; p[0].val = 0.2; p[0].normMin = 0.0; p[0].normMax = 0.5
	return


def _par(scriptOp, name, fallback):
	p = getattr(scriptOp.par, name, None)
	return p.eval() if p is not None else fallback


def _entry_allowed(px, py, resx, resy, keep_clear, corner_frac):
	"""The bottom edge is the audience's side of the frame: no cracks crawling in
	from there, but the two bottom corners are allowed (artist's direction).
	y is in PIL space here, so the bottom of the screen is py near resy."""
	if not keep_clear:
		return True
	on_bottom = py > resy * 0.92
	in_corner = px < resx * corner_frac or px > resx * (1.0 - corner_frac)
	return (not on_bottom) or in_corner


def _pick_entry(cx, cy, angle, resx, resy, keep_clear, corner_frac):
	"""Border point for this angle; if it lands on the forbidden bottom edge,
	rotate and try again, then give up (that crack is skipped)."""
	for k in range(12):
		a = angle + (0 if k == 0 else random.uniform(-60, 60))
		px, py = _border_point(cx, cy, a, resx, resy)
		if _entry_allowed(px, py, resx, resy, keep_clear, corner_frac):
			return px, py, a
	return None


def _walk_branch(x, y, cx, cy, frac, num_seg, width_px, offset_deg, segments, speckles):
	"""A side branch: leaves the parent crack at an angle and keeps that heading,
	so it reads as a branch rather than another spoke aimed at the centre."""
	dist = math.hypot(cx - x, cy - y)
	if dist < 1.0:
		return x, y
	angle = math.degrees(math.atan2(cy - y, cx - x)) + offset_deg
	step_len = dist * frac / max(1, num_seg)
	for i in range(num_seg):
		angle += random.uniform(-12, 12)
		this_len = step_len * random.uniform(0.75, 1.25)
		rad = math.radians(angle)
		nx, ny = x + math.cos(rad) * this_len, y + math.sin(rad) * this_len
		segments.append((x, y, nx, ny, max(1.0, width_px * (1.0 - i / max(1, num_seg) * 0.5))))
		if random.random() < 0.4:
			t = random.uniform(0.2, 0.8)
			speckles.append((x + (nx - x) * t, y + (ny - y) * t, random.uniform(1.0, 2.0)))
		x, y = nx, ny
	return x, y


def _walk_inward(x, y, cx, cy, frac, num_seg, width_px, segments, speckles):
	"""Walks from (x, y) toward the centre (cx, cy), covering `frac` of the
	remaining distance in `num_seg` wobbly steps. Wider at the outside, thinner
	as it closes in - the pressure is coming from the room toward the person."""
	dx, dy = cx - x, cy - y
	dist = math.hypot(dx, dy)
	if dist < 1.0:
		return x, y, math.degrees(math.atan2(dy, dx))
	angle = math.degrees(math.atan2(dy, dx))
	step_len = dist * frac / max(1, num_seg)
	for i in range(num_seg):
		# re-aim at the centre each step, then wander a little around that heading
		angle = math.degrees(math.atan2(cy - y, cx - x)) + random.uniform(-16, 16)
		this_len = step_len * random.uniform(0.8, 1.2)
		rad = math.radians(angle)
		nx = x + math.cos(rad) * this_len
		ny = y + math.sin(rad) * this_len
		this_width = max(1.0, width_px * (1.0 - i / max(1, num_seg) * 0.4))
		segments.append((x, y, nx, ny, this_width))
		if random.random() < 0.5:
			t = random.uniform(0.15, 0.85)
			speckles.append((x + (nx - x) * t + random.uniform(-3, 3),
							 y + (ny - y) * t + random.uniform(-3, 3),
							 random.uniform(1.3, 2.8)))
		x, y = nx, ny
	return x, y, angle


def _border_point(cx, cy, angle_deg, resx, resy):
	"""Where a ray from the centre at this angle leaves the frame."""
	rad = math.radians(angle_deg)
	dx, dy = math.cos(rad), math.sin(rad)
	ts = []
	if abs(dx) > 1e-6:
		ts += [((resx if dx > 0 else 0) - cx) / dx]
	if abs(dy) > 1e-6:
		ts += [((resy if dy > 0 else 0) - cy) / dy]
	t = min([v for v in ts if v > 0] or [max(resx, resy)])
	return cx + dx * t * 0.98, cy + dy * t * 0.98


def _seed(cx, cy, scale, resx, resy, segments, speckles, wmul=1.0, keep_clear=True, corner_frac=0.2):
	"""First feed: cracks appear at the EDGES of the frame, all around, and
	start closing in on the person. (Earlier this was the opposite - an impact
	fracture radiating out from the mouth; changed on the artist's direction so
	the pressure reads as coming from the room toward the caregiver.)"""
	num_radial = random.randint(6, 8)
	base_angle = random.uniform(0, 360)
	step = 360.0 / num_radial
	width = (0.011 + 0.015 * scale) * resy * wmul

	angles, tips = [], []
	for i in range(num_radial):
		a = base_angle + i * step + random.uniform(-14, 14)
		entry = _pick_entry(cx, cy, a, resx, resy, keep_clear, corner_frac)
		if entry is None:
			continue
		sx, sy, a = entry
		tx, ty, ta = _walk_inward(sx, sy, cx, cy, 0.42, random.randint(3, 5), width, segments, speckles)
		angles.append(ta)
		tips.append((tx, ty))

	_state['origin'] = (cx, cy)
	_state['radial_angles'] = angles
	_state['radial_tips'] = tips
	_state['tip_gen'] = [0] * len(tips)


def _grow(scale, resx, resy, segments, speckles, wmul=1.0, keep_clear=True, corner_frac=0.2):
	"""A later feed: ring the current inner ends together (a concentric fracture
	ring, like glass under pressure), then push every crack further INWARD, so
	the ring of damage visibly tightens around the person with each feed."""
	if not _state['radial_tips'] or _state['origin'] is None:
		return
	cx, cy = _state['origin']
	old_tips = list(_state['radial_tips'])
	n = len(old_tips)
	ring_width = (0.006 + 0.007 * scale) * resy * wmul

	if _state.get('style') == 'branch':
		# Branching style (no rings, so it never reads as a spider web): each crack
		# closes in further and may sprout a thinner side branch on the way, so the
		# pattern gets denser as it approaches the person.
		stop_r = 0.06 * resy
		gens = _state.get('tip_gen') or [0] * len(old_tips)
		new_tips, new_gens = [], []
		for i, (tx, ty) in enumerate(old_tips):
			g = gens[i] if i < len(gens) else 0
			w = (0.010 + 0.014 * scale) * resy * wmul * (0.72 ** g)
			if math.hypot(cx - tx, cy - ty) <= stop_r:
				new_tips.append((tx, ty)); new_gens.append(g); continue
			ntx, nty, na = _walk_inward(tx, ty, cx, cy, 0.45, random.randint(2, 4), w, segments, speckles)
			new_tips.append((ntx, nty)); new_gens.append(g)
			if i < len(_state['radial_angles']):
				_state['radial_angles'][i] = na
			if len(new_tips) < 22 and random.random() < 0.55 and len(segments) < MAX_SEGMENTS:
				off = random.choice([-1, 1]) * random.uniform(26, 52)
				bx, by = _walk_branch(tx, ty, cx, cy, 0.30, random.randint(2, 3), w * 0.7, off, segments, speckles)
				new_tips.append((bx, by)); new_gens.append(g + 1)
				_state['radial_angles'].append(math.degrees(math.atan2(cy - by, cx - bx)))
		_state['radial_tips'] = new_tips
		_state['tip_gen'] = new_gens
		return

	# 1. jagged ring connecting adjacent inner ends at their current reach
	for i in range(n):
		x0, y0 = old_tips[i]
		x1, y1 = old_tips[(i + 1) % n]
		mx = (x0 + x1) / 2.0 + random.uniform(-resy * 0.02, resy * 0.02)
		my = (y0 + y1) / 2.0 + random.uniform(-resy * 0.02, resy * 0.02)
		segments.append((x0, y0, mx, my, ring_width))
		segments.append((mx, my, x1, y1, ring_width))
		if random.random() < 0.6:
			speckles.append(((x0 + mx) / 2.0, (y0 + my) / 2.0, random.uniform(1.2, 2.4)))

	# 2. close every crack further in, but never quite reach the person
	width = (0.008 + 0.012 * scale) * resy * wmul
	stop_r = 0.06 * resy
	new_tips = []
	for i, (tx, ty) in enumerate(old_tips):
		if math.hypot(cx - tx, cy - ty) <= stop_r:
			new_tips.append((tx, ty))
			continue
		ntx, nty, na = _walk_inward(tx, ty, cx, cy, 0.45, random.randint(2, 4), width, segments, speckles)
		new_tips.append((ntx, nty))
		_state['radial_angles'][i] = na
	_state['radial_tips'] = new_tips

	# 3. occasionally a fresh crack starts at the edge in a gap, so later feeds
	# also make the encirclement denser, not just tighter
	if len(_state['radial_tips']) < 14 and random.random() < 0.4:
		i = random.randrange(n)
		a0 = _state['radial_angles'][i]
		a1 = _state['radial_angles'][(i + 1) % n]
		new_a = a0 + ((a1 - a0) % 360.0) / 2.0
		entry = _pick_entry(cx, cy, new_a, resx, resy, keep_clear, corner_frac)
		if entry is None:
			return
		sx, sy, new_a = entry
		ntx, nty, na = _walk_inward(sx, sy, cx, cy, 0.42, random.randint(3, 5), width, segments, speckles)
		_state['radial_angles'].insert(i + 1, na)
		_state['radial_tips'].insert(i + 1, (ntx, nty))


def _render(segments, speckles, resx, resy, keep_clear=True, corner_frac=0.2):
	img = Image.new('L', (resx, resy), 0)
	draw_ctx = ImageDraw.Draw(img)
	for (x0, y0, x1, y1, w) in segments:
		draw_ctx.line([(x0, y0), (x1, y1)], fill=255, width=max(1, int(round(w))))
	for (sx, sy, sr) in speckles:
		draw_ctx.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=255)
	mask = np.asarray(img, dtype=np.float32) / 255.0
	if keep_clear:
		# Cracks may enter from the sides and still cross the bottom of the frame,
		# so the bottom strip is cleared here at render time too - entry rules alone
		# were not enough. The two corners stay (artist's direction), and the cut is
		# feathered so it does not read as a straight editing line.
		h, w = mask.shape
		y0 = int(h * 0.90)
		fade = np.clip((np.arange(h) - y0) / max(1.0, h * 0.06), 0.0, 1.0)[:, None]
		x = np.arange(w)[None, :]
		cw = max(1.0, w * corner_frac)
		corner = np.clip(np.minimum(x, w - 1 - x) / cw, 0.0, 1.0)      # 0 at the corners, 1 in the middle
		mask = mask * (1.0 - fade * corner)
	return np.flipud(mask)  # PIL row0=top -> TD numpyArray row0=bottom


def onCook(scriptOp):
	now = absTime.seconds
	resx, resy = int(scriptOp.par.resolutionw.eval()), int(scriptOp.par.resolutionh.eval())

	sw = op(SWITCH_PATH)
	is_active_scene = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if is_active_scene and not _state['was_active']:
		# entering Act 2: a new visitor gets a fresh, uncracked surface. The previous
		# crack has already been snapshotted by Act 3's kintsugiDraw1 if it was used.
		_state.update({
			'prev_recoil_active': False, 'segments': [], 'speckles': [], 'origin': None,
			'radial_angles': [], 'radial_tips': [], 'mask': None, 'flash_start': None, 'hit_count': 0,
			'entry_frame': True,
		})
	_state['was_active'] = is_active_scene
	if not is_active_scene:
		# a different act is on screen - don't keep re-uploading a full
		# frame every cook for nothing
		blank = np.zeros((4, 4, 4), dtype=np.float32)
		scriptOp.copyNumpyArray(blank)
		return

	recoil = 0.0

	try:
		rc = op(RECOIL_PATH)
		if rc is not None:
			recoil = rc['recoil'].eval()
		fs = op(FEED_PATH)
		target = int(round(fs.fetch('feed_count_pub', 0.0))) if fs is not None else 0
		if _state['entry_frame']:
			# feedingState1 may not have zeroed last visitor's count yet this frame
			_state['entry_frame'] = False
			target = 0
		try:
			escalate = float(op(RECOIL_PATH).par.callbacks.eval().module.ESCALATE_FEEDS)
		except Exception:
			escalate = 3.0
		# The crack belongs to the OUTBURST, not to the feeding itself. Unity's
		# feeding level counts to 3 while Feedstoburst is 4, so feeding alone never
		# starts it: the crack arrives with 「我真的受不了了！」, together with the red
		# flood, and grows straight to the extent a full feed count would have given.
		# Lowering Feedstoburst back to 3 restores the old feed-driven behaviour.
		burst = fs is not None and fs.fetch('burst_pub', 0.0) > 0.5
		try:
			thr = int(round(op('/project1/effect_controller/effectController1').par.Feedstoburst.eval()))
		except Exception:
			thr = 3
		feed_may_burst = True
		if fs is not None and hasattr(fs.par, 'Burstmode'):
			feed_may_burst = str(fs.par.Burstmode.eval()) in ('feed', 'both')
		if burst:
			target = max(target, int(round(escalate)))
		elif (not feed_may_burst) or target < thr:
			# with Burstmode 'line' the cracks belong to the line alone: an
			# extra feed must not start drawing them before the outburst.
			target = 0
		_state['style'] = _par(scriptOp, 'Crackstyle', 'branch')
		grew = False
		while _state['hit_count'] < target and len(_state['segments']) < MAX_SEGMENTS:
			scale = max(0.0, min(1.0, (_state['hit_count'] + 1) / escalate))
			if not _state['segments']:
				mouth = op(MOUTH_PATH)
				ox = mouth['mouth_x'].eval() if mouth is not None else 0.5
				oy = mouth['mouth_y'].eval() if mouth is not None else 0.5
				_seed(ox * resx, (1.0 - oy) * resy, scale, resx, resy, _state['segments'], _state['speckles'],
					_par(scriptOp, 'Linewidthmul', 0.5), _par(scriptOp, 'Keepbottomclear', True), _par(scriptOp, 'Cornerfrac', 0.2))
			else:
				_grow(scale, resx, resy, _state['segments'], _state['speckles'],
					_par(scriptOp, 'Linewidthmul', 0.5), _par(scriptOp, 'Keepbottomclear', True), _par(scriptOp, 'Cornerfrac', 0.2))
			_state['hit_count'] += 1
			grew = True
		if grew:
			_state['mask'] = _render(_state['segments'], _state['speckles'], resx, resy,
				_par(scriptOp, 'Keepbottomclear', True), _par(scriptOp, 'Cornerfrac', 0.2))
			_state['flash_start'] = now
	except Exception as e:
		scriptOp.store('last_error', str(e))

	flash = 0.0
	if _state['flash_start'] is not None:
		fdt = now - _state['flash_start']
		flash = max(0.0, 1.0 - fdt / FLASH_DUR)

	mask = _state['mask']
	if mask is None or mask.shape != (resy, resx):
		mask = np.zeros((resy, resx), dtype=np.float32)

	# once part of the crack exists it holds at PERSISTENT_ALPHA as a
	# permanent scar - UNLESS it has spread HEAL_AFTER_HITS times or more,
	# in which case pressing the clouds down (weary_effective easing to 0)
	# also fades the crack back out, in step with the clouds clearing
	base = 0.0
	if _state['segments']:
		base = PERSISTENT_ALPHA
		if _state['hit_count'] >= HEAL_AFTER_HITS:
			# fade with actual pressing progress (relief), NOT weary_effective -
			# weary_effective is 0 whenever weary itself hasn't turned on yet
			# (feeding_count <= 3), which has nothing to do with whether the
			# hands have pressed anything; using it here made the crack look
			# like it vanished on its own the instant hit 3 landed
			try:
				weary_op = op(WEARY_PATH)
				relief = weary_op['relief'].eval() if weary_op is not None else 0.0
			except Exception:
				relief = 0.0
			base *= max(0.0, 1.0 - min(1.0, relief))
	alpha = mask * max(base, recoil)
	boost = 1.0 + 2.2 * flash
	r = alpha * min(3.2, 1.0 * boost)
	g = alpha * min(3.2, 0.95 * boost)
	b = alpha * min(3.2, 0.9 * boost)
	out = np.stack([r, g, b, alpha], axis=2).astype(np.float32)
	scriptOp.copyNumpyArray(out)
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
