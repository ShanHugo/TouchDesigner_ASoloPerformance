"""
Script CHOP Callbacks - ceremony_light/rippleTrigger1

Detects a rising-edge crossing of ritual_score above a threshold and drives a
single fixed-duration ripple animation (progress 0->1 once per trigger), not
a persisting/accumulating feedback loop - safe against runaway fill. Repeats
every Repeatinterval seconds while ritual_score stays sustained above the
threshold.

Also tracks, per continuous joined session: how many ripples fired. If the
session reaches N ripples and the hands are then released (ritual_score
falls back below threshold), a one-shot "split" animation opens (0->1),
used downstream to fan the light out into 5 points. If the hands rejoin
while split, a "merge" animation closes it back (current value -> 0), so
the 5 points re-converge on wherever the (re-tracked) hand position now is.

Outputs:
  ripple_active    - 1.0 while the current ripple animation is playing
  ripple_progress  - 0..1 through the ripple's fixed duration
  split_progress   - 0..1, how "open" the 5-point split is right now
                      (bidirectional: animates toward 1 on split-open,
                      toward 0 on split-close/merge)

me - this DAT
scriptOp - the OP which is cooking
"""

RITUAL_PATH = '/project1/care_first_state/decay_control/decayOut1'
LINETRACK_PATH = '/project1/scene_director/lineTrack1'

_state = {
	'prev_ritual_above': False,
	'triggered_at': None,
	'last_trigger_time': None,
	'ripple_count': 0,
	'had_3_ripples': False,
	# generic bidirectional animation state for the split
	'anim_value': 0.0,
	'anim_start_value': 0.0,
	'anim_target': 0.0,
	'anim_start_time': None,
	'line_split_open': False,
	'line_started_at': None,
}


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('Ripple')
	p = page.appendFloat('Triggerthreshold', label='Trigger Threshold (ritual_score)')
	p[0].default = 0.5
	p[0].val = 0.5
	p = page.appendFloat('Rippleduration', label='Ripple Duration (s)')
	p[0].default = 1.6
	p[0].val = 1.6
	p = page.appendFloat('Repeatinterval', label='Repeat Interval While Sustained (s)')
	p[0].default = 5.0
	p[0].val = 5.0
	page2 = scriptOp.appendCustomPage('Split')
	p = page2.appendMenu('Splitmode', label='What Opens The 5 Lights')
	p[0].menuNames = ['line', 'gesture', 'both']
	p[0].menuLabels = ['Subtitle line (reliable)', 'Ripple gesture (original)', 'Either']
	p[0].default = 'line'
	p[0].val = 'line'
	p = page2.appendInt('Splitonline', label='Act 1 Line That Lights The Candles')
	p[0].default = 2
	p[0].val = 2
	p[0].normMin = 1
	p[0].normMax = 3
	p = page2.appendFloat('Splitlinedelay', label='Delay After That Line Starts (s)')
	p[0].default = 0.0
	p[0].val = 0.0
	p[0].normMin = 0.0
	p[0].normMax = 30.0
	p = page2.appendInt('Splitripplecount', label='Ripples Needed to Enable Split')
	p[0].default = 3
	p[0].val = 3
	p = page2.appendFloat('Splitstagger', label='Delay Between Candles (fraction of the open)')
	p[0].default = 0.25
	p[0].val = 0.25
	p[0].normMin = 0.0
	p[0].normMax = 0.45
	p = page2.appendFloat('Splitopenduration', label='Split Open Duration (s)')
	p[0].default = 2.0
	p[0].val = 2.0
	p = page2.appendFloat('Splitcloseduration', label='Split Merge/Close Duration (s)')
	p[0].default = 1.4
	p[0].val = 1.4
	return


def onPulse(par):
	return


def _set_anim_target(target, now):
	if _state['anim_target'] != target:
		_state['anim_start_value'] = _state['anim_value']
		_state['anim_target'] = target
		_state['anim_start_time'] = now


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	ritual_chop = op(RITUAL_PATH)
	ritual = ritual_chop['ritual_score'].eval() if ritual_chop is not None else 0.0
	threshold = scriptOp.par.Triggerthreshold.eval()
	duration = max(scriptOp.par.Rippleduration.eval(), 0.05)
	repeat_interval = max(scriptOp.par.Repeatinterval.eval(), 0.1)
	ripples_needed = scriptOp.par.Splitripplecount.eval()
	open_duration = max(scriptOp.par.Splitopenduration.eval(), 0.05)
	close_duration = max(scriptOp.par.Splitcloseduration.eval(), 0.05)

	now = absTime.seconds
	above = ritual >= threshold
	was_above = _state['prev_ritual_above']

	mode = str(scriptOp.par.Splitmode.eval())
	gesture_can_split = mode in ('gesture', 'both')

	if above:
		last = _state['last_trigger_time']
		if last is None or (now - last) >= repeat_interval:
			_state['triggered_at'] = now
			_state['last_trigger_time'] = now
			_state['ripple_count'] += 1
			if _state['ripple_count'] >= ripples_needed:
				_state['had_3_ripples'] = True

		# merging is allowed ONLY in pure gesture mode. In 'both' the subtitle can
		# open the candles and the line logic latches, so a rejoin that closed them
		# would leave the act with no way to light them again.
		if mode == 'gesture' and not was_above and _state['anim_target'] > 0.5:
			# rising edge (hands rejoined) while currently split/opening -> merge
			_set_anim_target(0.0, now)
	else:
		if was_above:
			# falling edge: hands just released
			if gesture_can_split and _state['had_3_ripples']:
				_set_anim_target(1.0, now)
			_state['ripple_count'] = 0
			_state['had_3_ripples'] = False
		_state['last_trigger_time'] = None

	# --- subtitle-driven split (default). The 5 lights read as candles being lit,
	# and that beat belongs to the vow, not to a gesture the visitor may never
	# complete: 3 ripples in one joined session simply failed too often.
	if mode in ('line', 'both'):
		lt = op(LINETRACK_PATH)
		act_ch = lt['td_act'] if lt is not None else None
		line_ch = lt['td_line'] if lt is not None else None
		act = int(round(act_ch.eval())) if act_ch is not None else 0
		line = int(round(line_ch.eval())) if line_ch is not None else 0
		want = int(scriptOp.par.Splitonline.eval())
		if act == 1 and line >= want:
			if _state['line_started_at'] is None:
				_state['line_started_at'] = now
			if (now - _state['line_started_at']) >= scriptOp.par.Splitlinedelay.eval():
				if not _state['line_split_open']:
					_state['line_split_open'] = True
					_set_anim_target(1.0, now)
		else:
			# back before that line (a restart) or out of Act 1: close again
			_state['line_started_at'] = None
			if _state['line_split_open']:
				_state['line_split_open'] = False
				_set_anim_target(0.0, now)

	_state['prev_ritual_above'] = above

	# advance the bidirectional split animation
	target = _state['anim_target']
	start_time = _state['anim_start_time']
	if start_time is None:
		_state['anim_value'] = target
	else:
		dur = open_duration if target > _state['anim_start_value'] else close_duration
		t = min((now - start_time) / dur, 1.0)
		_state['anim_value'] = _state['anim_start_value'] + (target - _state['anim_start_value']) * t

	split_progress = _state['anim_value']

	triggered_at = _state['triggered_at']
	if triggered_at is not None:
		elapsed = now - triggered_at
		progress = min(elapsed / duration, 1.0)
		active = 1.0 if elapsed <= duration else 0.0
	else:
		progress = 1.0
		active = 0.0

	# candles are lit one at a time from the centre outward, not fanned out all at
	# once: each light gets its own progress, delayed by its distance from the
	# centre (splitLight0..4 sit at offsets -2, -1, 0, +1, +2)
	try:
		stagger = max(0.0, min(0.45, scriptOp.par.Splitstagger.eval()))
	except Exception:
		stagger = 0.0
	groups = [2, 1, 0, 1, 2]
	span = max(0.05, 1.0 - 2.0 * stagger)
	per_light = []
	for g in groups:
		p = (split_progress - g * stagger) / span
		per_light.append(max(0.0, min(1.0, p)))

	out_chans = [
		('ripple_active', active),
		('ripple_progress', progress),
		('split_progress', split_progress),
	]
	for i, v in enumerate(per_light):
		out_chans.append(('split_p%d' % i, v))
	for name, val in out_chans:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
