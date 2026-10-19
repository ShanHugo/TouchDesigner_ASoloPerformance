"""
Script CHOP Callbacks - emotional_fx/pulseValue1

Heartbeat pulse driving the ECG-style scanning line and the chest ripple.
The heartbeat is driven DIRECTLY by detected body activity (how far the
wrist has swung over a short recent window, per poseTrack1) rather than a
fixed idle rate: the more the person physically moves, the FASTER and
BIGGER the heart beats, with random (not metronomic) timing and amplitude.
Standing still (activity below Minactivityforbeat) produces no heartbeat
at all - not even a slow idle one. A continuous low-amplitude wobble runs
under everything so the line never looks totally dead, like a music
player's level display.

Outputs:
  pulse            - 0..1 instantaneous waveform value (idle wobble, or a
                      P-QRS-T spike during a beat)
  pulse_prev       - previous frame's pulse, for drawing a connected line
  activity         - 0..1 smoothed body-movement level
  ripple_progress  - 0..1, time since the last beat as a fraction of
                      Rippleduration (1.0 = no beat recently / ripple over)
  last_beat_amp    - size of the most recent beat (spike_amp_scale), held
                      until the next beat updates it - drives the chest
                      ripple's size

me - this DAT
scriptOp - the OP which is cooking
"""

import math
import random

POSE_PATH = '/project1/care_first_state/chest_alignment/poseTrack1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (0,)  # Act 1 only - the heartbeat/ECG is only ever shown there

OUTPUT_CHANS = ('pulse', 'pulse_prev', 'activity', 'ripple_progress', 'last_beat_amp')


# ---------------------------------------------------------------------------
# P-QRS-T waveform shape
# ---------------------------------------------------------------------------

def _bump(t, center, width, height):
	"""Smooth raised-cosine bump: 0 outside [center-width, center+width], continuous everywhere."""
	d = abs(t - center)
	if d >= width:
		return 0.0
	return height * 0.5 * (1.0 + math.cos(math.pi * d / width))


def _shape(t):
	"""Full P-QRS-T waveform value at fraction t (0..1 of one beat)."""
	return (
		_bump(t, 0.12, 0.10, 0.14) +   # P wave: small rounded bump
		_bump(t, 0.28, 0.03, -0.07) +  # Q: small dip before the spike
		_bump(t, 0.32, 0.055, 1.0) +   # R: sharp spike
		_bump(t, 0.37, 0.04, -0.16) +  # S: dip after the spike
		_bump(t, 0.65, 0.22, 0.26)     # T wave: wide rounded bump
	)


def _find_peak():
	"""One-time fine sweep to locate the true R-wave peak - a 60fps render
	sampling the analytic curve directly would often step clean over its
	~4ms-wide tip and land on the Q/S dips right next to it instead."""
	best_t, best_v = 0.32, 0.0
	for i in range(300):
		t = i / 299.0
		v = _bump(t, 0.32, 0.055, 1.0)  # search only the R lobe itself
		if v > best_v:
			best_v, best_t = v, t
	return best_t, max(0.0, _shape(best_t))


# ---------------------------------------------------------------------------
# persistent state
# ---------------------------------------------------------------------------

_state = {
	'prev_chest': None,
	'prev_wrist': None,
	'wrist_y_history': [],   # list of (time, wrist_y), for the range-based activity read
	'prev_time': None,
	'activity': 0.0,
	'last_beat': None,
	'next_beat_time': None,
	'beat_wrist_y': None,      # wrist height at the previous beat, for the displacement amplitude
	'wrist_y_now': None,
	'wrist_y_long': [],        # longer history, for net-travel vs path-length
	'torso_history': [],       # (t, chest_rel_x, chest_rel_y, tilt, head_y) in shoulder widths
	'spike_start': None,
	'spike_amp_scale': 1.0,
	'prev_pulse': 0.0,
	'peak_t': 0.32,           # fraction-of-beat where the true peak sits, found once per beat
	'peak_val': 1.0,          # the true shape() value there
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Pulse')
	p = page.appendFloat('Baseline', label='Idle Baseline Level')
	p[0].default = 0.03
	p[0].val = 0.03
	p[0].normMin = 0.0
	p[0].normMax = 0.3
	p = page.appendFloat('Baselineactivityboost', label='Baseline Lift From Activity')
	p[0].default = 0.06
	p[0].val = 0.06
	p[0].normMin = 0.0
	p[0].normMax = 0.3
	p = page.appendFloat('Spikeamp', label='Beat Spike Amplitude')
	p[0].default = 1.0
	p[0].val = 1.0
	p = page.appendFloat('Spikewidth', label='Spike Width (s)')
	p[0].default = 0.9
	p[0].val = 0.9
	p[0].normMin = 0.1
	p[0].normMax = 2.0
	p = page.appendFloat('Idleperiod', label='Idle Beat Interval (s, standing still)')
	p[0].default = 4.5
	p[0].val = 4.5
	p[0].normMin = 0.3
	p[0].normMax = 6.0
	p = page.appendFloat('Minperiod', label='Fastest Beat Interval (s, high activity)')
	p[0].default = 1.8
	p[0].val = 1.8
	p[0].normMin = 0.2
	p[0].normMax = 4.0
	p = page.appendFloat('Activitysmoothing', label='Activity Smoothing (higher = smoother/slower)')
	p[0].default = 3.0
	p[0].val = 3.0
	p[0].normMin = 0.5
	p[0].normMax = 10.0
	p = page.appendMenu('Movementsource', label='Which Body Part Drives The Heartbeat')
	p[0].menuNames = ['torso', 'wrist', 'auto']
	p[0].menuLabels = ['Upper body (reliable in a close framing)', 'Wrists (needs hands in frame)', 'Wrists when confident, else upper body']
	p[0].default = 'torso'
	p[0].val = 'torso'
	p = page.appendFloat('Torsodeadzone', label='Upper-Body Noise Floor (shoulder widths)')
	p[0].default = 0.02
	p[0].val = 0.02
	p[0].normMin = 0.0
	p[0].normMax = 0.2
	p = page.appendFloat('Torsoscale', label='Upper-Body Movement For A Full Beat (shoulder widths)')
	p[0].default = 0.18
	p[0].val = 0.18
	p[0].normMin = 0.02
	p[0].normMax = 1.0
	p = page.appendFloat('Wristconfmin', label='Min Wrist Confidence To Trust The Position')
	p[0].default = 0.25
	p[0].val = 0.25
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	p = page.appendFloat('Maxjump', label='Max Believable Jump Between Samples (shoulder widths)')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0.05
	p[0].normMax = 1.5
	p = page.appendFloat('Activityscale', label='Movement Sensitivity (lower = more sensitive)')
	p[0].default = 0.5
	p[0].val = 0.5
	p[0].normMin = 0.05
	p[0].normMax = 1.5
	p = page.appendFloat('Rangewindow', label='Movement Range Window (s)')
	p[0].default = 0.6
	p[0].val = 0.6
	p[0].normMin = 0.15
	p[0].normMax = 2.0
	p = page.appendFloat('Activitydeadzone', label='Tracking-Jitter Deadzone (movement/s ignored)')
	p[0].default = 0.12
	p[0].val = 0.12
	p[0].normMin = 0.0
	p[0].normMax = 0.5
	p = page.appendFloat('Activityresponsecurve', label='Activity Response Curve (>1 = stays calm until real movement)')
	p[0].default = 1.2
	p[0].val = 1.2
	p[0].normMin = 0.3
	p[0].normMax = 4.0
	p = page.appendMenu('Ampsource', label='What Sets The Beat Size')
	p[0].menuNames = ['displacement', 'activity']
	p[0].menuLabels = ['Net hand travel since the last beat', 'Overall movement (original)']
	p[0].default = 'displacement'
	p[0].val = 'displacement'
	p = page.appendFloat('Ampwindow', label='Window For Net Hand Travel (s)')
	p[0].default = 1.5
	p[0].val = 1.5
	p[0].normMin = 0.3
	p[0].normMax = 4.0
	p = page.appendFloat('Ampstraightness', label='How Directed The Travel Must Be (net/path)')
	p[0].default = 0.55
	p[0].val = 0.55
	p[0].normMin = 0.1
	p[0].normMax = 1.0
	p = page.appendFloat('Ampdisplacement', label='Hand Travel That Counts As A Full Beat')
	p[0].default = 0.22
	p[0].val = 0.22
	p[0].normMin = 0.05
	p[0].normMax = 0.8
	p = page.appendFloat('Spikeampmin', label='Beat Size At Zero Activity')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	p = page.appendFloat('Spikeampmax', label='Beat Size At Full Activity')
	p[0].default = 2.2
	p[0].val = 2.2
	p[0].normMin = 0.5
	p[0].normMax = 2.0
	p = page.appendFloat('Randomtiming', label='Random Timing Jitter (0..1, fraction of interval)')
	p[0].default = 0.45
	p[0].val = 0.45
	p[0].normMin = 0.0
	p[0].normMax = 0.9
	p = page.appendFloat('Randomamp', label='Random Amplitude Jitter (0..1)')
	p[0].default = 0.3
	p[0].val = 0.3
	p[0].normMin = 0.0
	p[0].normMax = 0.9
	p = page.appendFloat('Minactivityforbeat', label='Min Activity To Beat At All (below = silent)')
	p[0].default = 0.04
	p[0].val = 0.04
	p[0].normMin = 0.0
	p[0].normMax = 0.3
	p = page.appendFloat('Wobbleamp', label='Idle Wobble Amplitude (music-visualizer style)')
	p[0].default = 0.02
	p[0].val = 0.02
	p[0].normMin = 0.0
	p[0].normMax = 0.15
	p = page.appendFloat('Rippleduration', label='Ripple Duration (s)')
	p[0].default = 1.2
	p[0].val = 1.2
	p[0].normMin = 0.2
	p[0].normMax = 3.0
	return


# ---------------------------------------------------------------------------
# onCook, broken into one function per concern so a future change to one
# stays local instead of risking the others
# ---------------------------------------------------------------------------

def _is_active_scene():
	sw = op(SWITCH_PATH)
	return sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES


def _emit(scriptOp, pulse, pulse_prev, activity, ripple_progress, last_beat_amp):
	values = dict(pulse=pulse, pulse_prev=pulse_prev, activity=activity,
		ripple_progress=ripple_progress, last_beat_amp=last_beat_amp)
	for name in OUTPUT_CHANS:
		chan = scriptOp.appendChan(name)
		chan[0] = values[name]


def _update_activity(scriptOp, now, dt):
	"""Reads poseTrack1, updates _state['activity'] from the wrist's recent
	movement RANGE (robust to a few dropped/frozen frames during a fast
	real gesture, unlike frame-to-frame velocity), and returns whether a
	person is currently tracked at all."""
	found = False
	try:
		pose = op(POSE_PATH)
		found = pose['pose_found'].eval() > 0.5 if pose is not None else False
		if found:
			chest = (pose['chest_x'].eval(), pose['chest_y'].eval())
			wrist = (pose['wrist_mid_x'].eval(), pose['wrist_mid_y'].eval())

			# frame-to-frame VELOCITY is fragile: a fast real wave causes
			# motion blur, which drops MediaPipe's wrist confidence right at
			# the exact moment (and extremes) that matter most, freezing the
			# tracked position for those frames - no amount of sensitivity
			# tuning helps if the position data itself didn't move. Instead,
			# track the RANGE the wrist has covered over a short rolling
			# window: as long as SOME frames near the top and bottom of a
			# wave got through, the range still captures the full swing even
			# if several frames in between were dropped/frozen.
			# measure the swing in BODY units (shoulder widths), not frame
			# fractions: the same gesture now reads the same whether the visitor
			# stands near or far, and 'how big was that movement' finally means
			# something absolute
			rel = pose['wrist_rel_y']
			wy = rel.eval() if rel is not None else wrist[1]

			# Only trust the wrist when MediaPipe actually saw it. With the current
			# framing (hands below the bottom of frame) confidence sat at 0.13 and
			# the position teleported up to 0.65 shoulder widths between samples -
			# noise alone exceeded the full-scale threshold, so the heart was
			# permanently at maximum (artist: "完全不準，一直在大心跳").
			lwc = pose['debug_lw_conf']
			rwc = pose['debug_rw_conf']
			conf = max(lwc.eval() if lwc is not None else 0.0,
					   rwc.eval() if rwc is not None else 0.0)
			conf_min = scriptOp.par.Wristconfmin.eval() if hasattr(scriptOp.par, 'Wristconfmin') else 0.0
			prev_y = _state['wrist_y_history'][-1][1] if _state['wrist_y_history'] else wy
			max_jump = scriptOp.par.Maxjump.eval() if hasattr(scriptOp.par, 'Maxjump') else 0.35
			if conf >= conf_min and abs(wy - prev_y) <= max_jump:
				_state['wrist_y_history'].append((now, wy))
			_state['wrist_conf'] = conf

			# --- upper-body track: with the hands out of frame this is the only
			# thing measured rather than guessed. Everything in shoulder widths.
			def _c(nm, dflt=0.0):
				ch = pose[nm]
				return ch.eval() if ch is not None else dflt
			_state['torso_history'].append((now, _c('chest_rel_x'), _c('chest_rel_y'),
											_c('shoulder_tilt'), _c('head_rel_y')))
			tw = max(0.2, scriptOp.par.Rangewindow.eval())
			tcut = now - tw
			while _state['torso_history'] and _state['torso_history'][0][0] < tcut:
				_state['torso_history'].pop(0)
			window = max(0.2, scriptOp.par.Rangewindow.eval())
			cutoff = now - window
			while _state['wrist_y_history'] and _state['wrist_y_history'][0][0] < cutoff:
				_state['wrist_y_history'].pop(0)

			if len(_state['wrist_y_history']) >= 4:
				ys = sorted(y for (_, y) in _state['wrist_y_history'])
				# a percentile span, not max-min: one bad landmark frame used to
				# define the whole movement range
				lo = ys[max(0, int(len(ys) * 0.1))]
				hi = ys[min(len(ys) - 1, int(len(ys) * 0.9))]
				wrist_range = hi - lo
			elif len(_state['wrist_y_history']) >= 2:
				ys = [y for (_, y) in _state['wrist_y_history']]
				wrist_range = max(ys) - min(ys)
			else:
				wrist_range = 0.0

			_state['prev_chest'] = chest
			_state['prev_wrist'] = wrist
			_state['wrist_y_now'] = wy
			# a second, longer history just for the beat SIZE: waving covers a lot
			# of path but ends up where it started, a reach does not
			longw = scriptOp.par.Ampwindow.eval() if hasattr(scriptOp.par, 'Ampwindow') else 1.5
			_state['wrist_y_long'].append((now, wy))
			lcut = now - max(0.3, longw)
			while _state['wrist_y_long'] and _state['wrist_y_long'][0][0] < lcut:
				_state['wrist_y_long'].pop(0)

			source = str(scriptOp.par.Movementsource.eval()) if hasattr(scriptOp.par, 'Movementsource') else 'wrist'
			use_torso = (source == 'torso') or (source == 'auto' and conf < conf_min)
			if use_torso:
				th = _state['torso_history']
				if len(th) >= 4:
					xs = sorted(r[1] for r in th)
					ys = sorted(r[2] for r in th)
					ts_ = sorted(r[3] for r in th)
					hs = sorted(r[4] for r in th)

					def _span(v):
						lo = v[max(0, int(len(v) * 0.1))]
						hi = v[min(len(v) - 1, int(len(v) * 0.9))]
						return hi - lo
					# Weighted by MEASURED signal-to-noise while standing still, not by
					# intuition. Standing-still spans: chest-x 0.0088, chest-y 0.0154,
					# head 0.0247, shoulder tilt 0.0359; a big sway gives chest-x
					# 0.3605 and tilt 0.4405. So chest-x separates 41:1 while tilt is
					# only 12:1 - and at a GENTLE sway the tilt (0.0311) is actually
					# below its own standing-still noise, i.e. useless. Chest travel
					# leads; the noisier parts are kept only as a small contribution.
					sway_x = _span(xs)
					sway_y = _span(ys)
					lean = _span(ts_)
					bob = _span(hs)
					move = sway_x + 0.3 * sway_y + 0.15 * bob + 0.1 * lean
				else:
					move = 0.0
				scale = max(0.02, scriptOp.par.Torsoscale.eval())
				deadzone = scriptOp.par.Torsodeadzone.eval()
			else:
				move = wrist_range
				scale = max(0.05, scriptOp.par.Activityscale.eval())
				deadzone = scriptOp.par.Activitydeadzone.eval()
			range_signal = max(0.0, move - deadzone)
			target = max(0.0, min(1.0, range_signal / scale))
			smoothing = max(0.5, scriptOp.par.Activitysmoothing.eval())
			# exponential ease toward the instantaneous movement reading -
			# rises fast on real movement, settles gradually when still
			alpha = 1.0 - math.exp(-dt * smoothing)
			_state['activity'] = _state['activity'] + (target - _state['activity']) * alpha
		else:
			_state['prev_chest'] = None
			_state['prev_wrist'] = None
			# no valid tracking this frame - ease activity back toward idle
			# rather than freezing or snapping
			_state['activity'] = max(0.0, _state['activity'] - dt * 0.5)
	except Exception as e:
		scriptOp.store('last_error', str(e))

	return found


def _maybe_trigger_beat(scriptOp, now, activity):
	"""Schedules the next beat (with random timing) and, if it's due,
	fires it: sets spike_start/spike_amp_scale/peak_t/peak_val for
	_render_pulse to use. Returns the activity-driven average period and
	the curved activity value, both reused for beat-size scaling."""
	idle_period = max(0.15, scriptOp.par.Idleperiod.eval())
	min_period = max(0.1, scriptOp.par.Minperiod.eval())
	# non-linear response curve: low activity stays close to the (very slow)
	# idle rate almost unchanged, only real/sustained movement pulls the
	# average period down toward min_period
	response_gamma = max(0.2, scriptOp.par.Activityresponsecurve.eval())
	activity_curved = activity ** response_gamma
	base_period = idle_period - activity_curved * (idle_period - min_period)

	min_activity = scriptOp.par.Minactivityforbeat.eval()
	if activity < min_activity:
		# essentially motionless - no heartbeat at all, not even a slow idle
		# one; keep pushing the next-beat schedule out so nothing fires the
		# instant activity dips back down, and reset it fresh once movement
		# actually resumes
		_state['next_beat_time'] = now + base_period
		return base_period, activity_curved

	if _state['next_beat_time'] is None:
		_state['next_beat_time'] = now + base_period

	if now >= _state['next_beat_time']:
		_state['last_beat'] = now
		_state['spike_start'] = now
		# amplitude also scales with activity (plus its own random wobble) -
		# a near-still body should barely register a beat at all, a big
		# movement should thump hard, and no two beats feel identical
		amp_min = scriptOp.par.Spikeampmin.eval()
		amp_max = scriptOp.par.Spikeampmax.eval()
		amp_jitter = scriptOp.par.Randomamp.eval()
		# Amplitude used to follow the same movement RANGE that drives the rate,
		# so simply waving an arm pinned every beat at maximum (artist, 9/30).
		# In 'displacement' mode the beat's size is how far the wrist actually
		# travelled between this beat and the previous one: waving returns to
		# where it started and reads small, a deliberate reach or lift reads big.
		# The rate still follows overall movement, so waving still speeds it up.
		src = str(scriptOp.par.Ampsource.eval()) if hasattr(scriptOp.par, 'Ampsource') else 'activity'
		amp_drive = activity_curved
		if src == 'displacement':
			# net travel over Ampwindow, weighted by how DIRECTED that travel was.
			# Sampling only the start/end at beat times aliased against the wave
			# rhythm (measured: waving 1.375 vs reaching 1.399 - no difference).
			# net / path separates them: a wave returns to where it started, so its
			# net is near zero however much path it covers.
			hist = _state.get('wrist_y_long') or []
			if len(hist) >= 3:
				ys = [y for (_, y) in hist]
				net = abs(ys[-1] - ys[0])
				path = 0.0
				for i in range(1, len(ys)):
					path += abs(ys[i] - ys[i - 1])
				straight = net / path if path > 1e-5 else 0.0
				dscale = max(0.02, scriptOp.par.Ampdisplacement.eval())
				sref = max(0.05, scriptOp.par.Ampstraightness.eval())
				amp_drive = max(0.0, min(1.0, net / dscale)) * max(0.0, min(1.0, straight / sref))
			else:
				amp_drive = 0.0
			_state['beat_wrist_y'] = _state.get('wrist_y_now')
		base_amp = amp_min + amp_drive * (amp_max - amp_min)
		_state['spike_amp_scale'] = max(0.05, base_amp * random.uniform(1.0 - amp_jitter, 1.0 + amp_jitter))
		_state['peak_t'], _state['peak_val'] = _find_peak()

		# schedule the NEXT beat with random jitter around the activity-driven
		# average interval, instead of a perfectly regular metronome - this
		# is what makes randomly waving an arm produce randomly-spaced beats
		# rather than a smooth, predictable heart-rate curve
		jitter = scriptOp.par.Randomtiming.eval()
		_state['next_beat_time'] = now + base_period * random.uniform(1.0 - jitter, 1.0 + jitter)

	return base_period, activity_curved


def _render_pulse(scriptOp, now, activity):
	"""Computes this frame's pulse value: idle baseline + wobble, with a
	P-QRS-T spike layered on top while a beat is in flight. Also returns
	ripple_progress/last_beat_amp for the chest-ripple visual."""
	baseline = scriptOp.par.Baseline.eval() + activity * scriptOp.par.Baselineactivityboost.eval()

	# continuous low-amplitude, high-frequency wobble on top of the baseline -
	# like a music player's waveform/level display, so the line never looks
	# perfectly dead even between beats. Sum of a few sines at unrelated
	# frequencies/phases reads as organic wobble without needing a noise lib.
	wobble_amp = scriptOp.par.Wobbleamp.eval()
	wobble = (
		math.sin(now * 2.7 + 1.3) * 0.4 +
		math.sin(now * 5.1 + 0.7) * 0.3 +
		math.sin(now * 8.3 + 2.1) * 0.3
	) * wobble_amp
	pulse = max(0.0, baseline + wobble)

	ripple_dur = max(0.1, scriptOp.par.Rippleduration.eval())
	if _state['spike_start'] is not None:
		ripple_progress = max(0.0, min(1.0, (now - _state['spike_start']) / ripple_dur))
	else:
		ripple_progress = 1.0
	last_beat_amp = _state['spike_amp_scale']

	if _state['spike_start'] is not None:
		sdt = now - _state['spike_start']
		total = max(0.05, scriptOp.par.Spikewidth.eval())
		if 0 <= sdt <= total:
			t = sdt / total
			amp = scriptOp.par.Spikeamp.eval() * _state['spike_amp_scale']
			shape = max(0.0, _shape(t))

			# force a fixed-duration plateau at the KNOWN true peak (found by
			# _find_peak() once, at beat onset) around the known peak time -
			# guaranteed wider than one render frame regardless of exactly
			# when frames happen to land, so the beat reliably reads as a
			# clean visible pulse instead of a handful of random undersampled
			# shoulder values. Kept narrow - wider starts flattening the
			# P/Q/S/T shape into a featureless plateau, the opposite of a
			# readable beat.
			PLATEAU_SECONDS = 0.035
			plateau_half = (PLATEAU_SECONDS / 2.0) / total
			if abs(t - _state['peak_t']) <= plateau_half:
				shape = max(shape, _state['peak_val'])

			spike = shape * amp
			pulse = max(pulse, spike)

	return pulse, ripple_progress, last_beat_amp


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	now = absTime.seconds

	if not _is_active_scene():
		# a different act is on screen - skip all pose reads/activity math and
		# just flatline; nothing reads this while it's not the active scene
		_emit(scriptOp, pulse=0.0, pulse_prev=0.0, activity=0.0, ripple_progress=1.0, last_beat_amp=0.0)
		_state['prev_time'] = now
		return

	dt = 0.0 if _state['prev_time'] is None else max(0.0, min(0.2, now - _state['prev_time']))
	_state['prev_time'] = now

	found = _update_activity(scriptOp, now, dt)
	activity = max(0.0, min(1.0, _state['activity']))

	# no person detected at all - this is meant to be a DIRECT reading of
	# body activity, so no body means no heartbeat, not a fake idle rate.
	# don't advance last_beat while absent, so the moment tracking resumes
	# it reads as overdue and beats right away rather than waiting out a
	# stale idle_period countdown that kept ticking while nobody was there
	if not found:
		_emit(scriptOp, pulse=0.0, pulse_prev=_state['prev_pulse'], activity=0.0, ripple_progress=1.0, last_beat_amp=0.0)
		_state['prev_pulse'] = 0.0
		return

	_maybe_trigger_beat(scriptOp, now, activity)
	pulse, ripple_progress, last_beat_amp = _render_pulse(scriptOp, now, activity)

	prev_pulse = _state['prev_pulse']
	_state['prev_pulse'] = pulse
	_emit(scriptOp, pulse=pulse, pulse_prev=prev_pulse, activity=activity,
		ripple_progress=ripple_progress, last_beat_amp=last_beat_amp)
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
