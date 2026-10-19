"""
Script TOP Callbacks - emotional_fx/ecgDraw1

Draws the scrolling ECG trace as one genuine smooth continuous polyline
using PIL (rounded joints, round end caps) instead of compositing a
rotated-rectangle segment per frame into a feedback-scroll loop - the old
approach always showed visible facets/seams at the joints, especially
during the sharp R-wave turn, and looked "not solid" instead of a real
line. This keeps a rolling buffer of recent pulse samples and redraws the
whole visible stroke fresh every cook.

me - this OP
scriptOp - the OP which is cooking
"""

import math
import numpy as np
from PIL import Image, ImageDraw

PULSE_PATH = '/project1/care_first_state/emotional_fx/pulseValue1'


def _par(o, name, default):
	try:
		p = getattr(o.par, name, None)
		return p.eval() if p is not None else default
	except Exception:
		return default

FX_PATH = '/project1/care_first_state/emotional_fx'
POSE_PATH = '/project1/care_first_state/chest_alignment/poseTrack1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (0,)  # Act 1 only

_state = {
	'history': [],   # list of (abs_time, pulse_value)
}


def _pulse_at(t_query, pv):
	"""Reconstruct what pulseValue1's output would have been at a past
	timestamp, by replaying its own formula against its live module state -
	this scene's actual achieved cook rate can be well under 60fps, so
	ecgDraw1 rarely gets enough real cooks on its own to sample the curve
	densely; backfilling several of these per cook keeps the drawn line
	smooth regardless of how often this node itself actually cooks."""
	pv_cb = op(pv.par.callbacks.eval())
	mod = pv_cb.module
	st = mod._state
	activity = pv['activity'].eval()
	pulse = pv.par.Baseline.eval() + activity * pv.par.Baselineactivityboost.eval()
	if st.get('spike_start') is not None:
		sdt = t_query - st['spike_start']
		total = max(0.05, pv.par.Spikewidth.eval())
		if 0 <= sdt <= total:
			t = sdt / total
			amp = pv.par.Spikeamp.eval() * st.get('spike_amp_scale', 1.0)
			shape = max(0.0, mod._shape(t))
			plateau_half = (0.035 / 2.0) / total
			if abs(t - st.get('peak_t', 0.32)) <= plateau_half:
				shape = max(shape, st.get('peak_val', 1.0))
			pulse = max(pulse, shape * amp)
	return pulse


def onCook(scriptOp):
	now = absTime.seconds
	resx = int(scriptOp.par.resolutionw.eval())
	resy = int(scriptOp.par.resolutionh.eval())

	# This node keeps CookLevel.ALWAYS, which means TD cooks it every frame even
	# when ecgSwitch1 is not selecting it - so the GPU path has to switch it off
	# here, not just downstream, or both renderers run and nothing is saved.
	fxc = op(FX_PATH)
	on_gpu = bool(fxc.par.Useecggpu.eval()) if (fxc is not None and hasattr(fxc.par, 'Useecggpu')) else False

	sw = op(SWITCH_PATH)
	is_active_scene = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if on_gpu or not is_active_scene:
		# a different act is on screen - skip the PIL redraw + history backfill
		# entirely (this was the single most expensive thing running every
		# frame regardless of which scene was actually visible) and just hold
		# a small cached blank frame
		_state['history'] = []
		blank = np.zeros((4, 4, 4), dtype=np.float32)
		scriptOp.copyNumpyArray(blank)
		return

	fx = op(FX_PATH)
	pv = op(PULSE_PATH)
	pose = op(POSE_PATH)
	found = pose['pose_found'].eval() > 0.5 if pose is not None else False

	last_t = _state['history'][-1][0] if _state['history'] else None
	if not found:
		pulse_now = 0.0
		_state['history'].append((now, 0.0))
	elif pv is None:
		pulse_now = 0.0
		_state['history'].append((now, 0.0))
	else:
		# backfill: replay the analytic curve at ~60fps steps between the
		# last recorded sample and now, instead of relying on this node
		# happening to cook that often itself
		step = 1.0 / 60.0
		start_t = last_t + step if last_t is not None else now
		n = 0
		tq = start_t
		while tq < now and n < 180:
			_state['history'].append((tq, _pulse_at(tq, pv)))
			tq += step
			n += 1
		pulse_now = _pulse_at(now, pv)
		_state['history'].append((now, pulse_now))

	scroll_seconds = max(0.2, fx.par.Scrollseconds.eval()) if fx is not None else 1.8
	cutoff = now - scroll_seconds - 0.15
	if len(_state['history']) > 900:
		_state['history'] = _state['history'][-900:]
	while _state['history'] and _state['history'][0][0] < cutoff:
		_state['history'].pop(0)

	xleft = fx.par.Ecgxleft.eval() if fx is not None else -0.5
	xright = fx.par.Ecgxright.eval() if fx is not None else 0.5
	ybase = fx.par.Ecgybase.eval() if fx is not None else 0.0
	yrange = fx.par.Ecgyrange.eval() if fx is not None else 0.3
	dotsize = fx.par.Dotsize.eval() if fx is not None else 0.02

	points = []
	for (t, v) in _state['history']:
		age = now - t
		frac_x = 1.0 - (age / scroll_seconds)
		if frac_x < -0.05:
			continue
		x_frac = xleft + frac_x * (xright - xleft)
		# soft limit: a linear map clipped every big beat against the top of this
		# TOP (measured: extent saturated at ~183 px whatever the beat size), so
		# large and huge beats looked identical. Small beats stay linear, big ones
		# compress into the remaining canvas instead of being cut flat.
		vv = v * yrange
		y_frac = ybase + 0.48 * (1.0 - math.exp(-2.2 * vv))
		# TD offset-fraction convention here is positive-y = up; PIL rows
		# run top(0) to bottom(resy) - convert once here at the source
		row_frac = 0.5 - y_frac
		px = (x_frac + 0.5) * resx
		py = row_frac * resy
		points.append((px, py))

	# The beat used to vary in HEIGHT only, and at this line width and brightness
	# that difference was hard to read (noted in the 2026-09-30 meeting: each
	# visitor's heartbeat is meant to look individual). Each segment is now drawn
	# with its own brightness AND width, scaled by the local pulse height, so a big
	# beat flares and thickens while the resting line stays as thin and dim as the
	# artist asked for.
	bmul = fx.par.Ecgbrightness.eval() if (fx is not None and hasattr(fx.par, 'Ecgbrightness')) else 1.0
	boost = _par(fx, 'Ecgbeatboost', 3.0)
	wmul = _par(fx, 'Ecgbeatwidth', 1.9)
	peakref = max(0.05, _par(fx, 'Ecgpeakref', 1.2))
	base_w = max(1.0, dotsize * resy)

	img = Image.new('L', (resx, resy), 0)
	if len(points) >= 2:
		draw_ctx = ImageDraw.Draw(img)
		vals = [v for (_, v) in _state['history']][-len(points):]
		for i in range(len(points) - 1):
			v = max(vals[i], vals[i + 1]) if i + 1 < len(vals) else 0.0
			norm = max(0.0, min(1.0, v / peakref))
			inten = max(0.0, min(1.0, bmul * (1.0 + boost * norm)))
			w = max(1, int(round(base_w * (1.0 + (wmul - 1.0) * norm))))
			draw_ctx.line([points[i], points[i + 1]], fill=int(round(inten * 255)),
						  width=w, joint='curve')
		r = base_w / 2.0
		for (px, py) in (points[0], points[-1]):
			draw_ctx.ellipse([px - r, py - r, px + r, py + r], fill=int(round(bmul * 255)))

	lit = np.asarray(img, dtype=np.float32) / 255.0
	lit = np.flipud(lit)          # PIL row0=top -> TD numpyArray row0=bottom
	mask = (lit > 0.002).astype(np.float32)   # coverage = alpha; lit already carries brightness
	r = lit * 1.2
	g = lit * 0.72
	b = lit * 0.55
	out = np.stack([r, g, b, mask], axis=2).astype(np.float32)
	scriptOp.copyNumpyArray(out)
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
