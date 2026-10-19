"""
Script CHOP Callbacks - emotional_fx/ecgHistory1

The sampling half of the ECG, split out of ecgDraw1 so the drawing half can be
a shader. This keeps exactly ecgDraw1's rolling history and its backfill (the
analytic replay of pulseValue1's own curve at 60 Hz, which is what makes the
trace smooth no matter how often anything actually cooks), but instead of
rasterising a 1024x384 polyline in PIL it just resamples that history onto a
fixed grid and hands it over as two channels:

  pulse  - the pulse value at that point of the scroll window
  valid  - 0 while the window is still filling after the act starts

Sample 0 is the OLDEST (left edge), sample N-1 is now (right edge), so the
shader can map pixel x straight to a sample index.

Act 1 only, same gate as before: outside it the history is dropped and the
channels go flat, so nothing accumulates while the trace is off screen.

me - this DAT
scriptOp - the OP which is cooking
"""

N = 256                      # grid points across the scroll window

PULSE_PATH = '/project1/care_first_state/emotional_fx/pulseValue1'
FX_PATH = '/project1/care_first_state/emotional_fx'
POSE_PATH = '/project1/care_first_state/chest_alignment/poseTrack1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (0,)  # Act 1 only

_state = {'history': []}     # list of (abs_time, pulse_value)


def _pulse_at(t_query, pv, mod, st):
	"""What pulseValue1 would have output at a past timestamp - its own formula
	replayed against its live module state. mod/st are hoisted out of the caller's
	loop; looking them up per sample was most of this function's cost."""
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
	scriptOp.clear()
	scriptOp.numSamples = N
	scriptOp.rate = 60
	ch_p = scriptOp.appendChan('pulse')
	ch_v = scriptOp.appendChan('valid')

	sw = op(SWITCH_PATH)
	active = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if not active:
		_state['history'] = []
		for i in range(N):
			ch_p[i] = 0.0
			ch_v[i] = 0.0
		return

	now = absTime.seconds
	fx = op(FX_PATH)
	pv = op(PULSE_PATH)
	pose = op(POSE_PATH)
	found = pose['pose_found'].eval() > 0.5 if pose is not None else False
	hist = _state['history']
	last_t = hist[-1][0] if hist else None

	if not found or pv is None:
		hist.append((now, 0.0))
	else:
		cb = op(pv.par.callbacks.eval())
		mod = cb.module
		st = mod._state
		step = 1.0 / 60.0
		tq = last_t + step if last_t is not None else now
		n = 0
		while tq < now and n < 180:
			hist.append((tq, _pulse_at(tq, pv, mod, st)))
			tq += step
			n += 1
		hist.append((now, _pulse_at(now, pv, mod, st)))

	scroll = max(0.2, fx.par.Scrollseconds.eval()) if fx is not None else 4.0
	cutoff = now - scroll - 0.15
	if len(hist) > 900:
		del hist[:len(hist) - 900]
	while hist and hist[0][0] < cutoff:
		hist.pop(0)
	_state['history'] = hist

	if not hist:
		for i in range(N):
			ch_p[i] = 0.0
			ch_v[i] = 0.0
		return

	# resample onto the grid; both sequences are time-ordered so one walk does it
	t0 = hist[0][0]
	j = 0
	hn = len(hist)
	for i in range(N):
		tg = now - scroll * (1.0 - i / float(N - 1))
		if tg < t0:
			ch_p[i] = 0.0
			ch_v[i] = 0.0
			continue
		while j + 1 < hn and hist[j + 1][0] < tg:
			j += 1
		if j + 1 < hn:
			ta, va = hist[j]
			tb, vb = hist[j + 1]
			f = (tg - ta) / (tb - ta) if tb > ta else 0.0
			ch_p[i] = va + (vb - va) * max(0.0, min(1.0, f))
		else:
			ch_p[i] = hist[-1][1]
		ch_v[i] = 1.0
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
