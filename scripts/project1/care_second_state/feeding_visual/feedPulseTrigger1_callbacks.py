"""
Script CHOP Callbacks - feeding_visual/feedPulseTrigger1

Drives a single fixed-duration pulse animation (progress 0->1) each time
feeding_triggered fires - a one-shot animation, not a persisting/feedback
loop, so it can't run away.

Outputs:
  pulse_active    - 1.0 while the current pulse animation is playing
  pulse_progress  - 0..1 through the pulse's fixed duration

me - this DAT
scriptOp - the OP which is cooking
"""

FEEDING_PATH = '/project1/care_second_state/feeding_state/feedingState1'

_state = {'triggered_at': None}


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('FeedPulse')
	p = page.appendFloat('Pulseduration', label='Pulse Duration (s)')
	p[0].default = 1.2
	p[0].val = 1.2
	return


def onPulse(par):
	return


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	feeding = op(FEEDING_PATH)
	# storage, not channels: cook dependency loop with feedingState1
	triggered = feeding.fetch('feed_trigger_pub', 0.0) if feeding is not None else 0.0
	feed_count = feeding.fetch('feed_count_pub', None) if feeding is not None else None
	if feed_count is None:
		count_chan = feeding['feeding_count'] if feeding is not None else None
		feed_count = count_chan.eval() if count_chan is not None else (_state.get('prev_count') or 0.0)
	duration = max(scriptOp.par.Pulseduration.eval(), 0.05)
	now = absTime.seconds

	# the one-frame feeding_triggered pulse is regularly missed because cook
	# order between these two script CHOPs is not guaranteed - watch the
	# monotonic counter as well so every feed lights the ring
	prev_count = _state.get('prev_count')
	if triggered > 0.5 or (prev_count is not None and feed_count > prev_count):
		_state['triggered_at'] = now
	_state['prev_count'] = feed_count

	triggered_at = _state['triggered_at']
	if triggered_at is not None:
		elapsed = now - triggered_at
		progress = min(elapsed / duration, 1.0)
		active = 1.0 if elapsed <= duration else 0.0
	else:
		progress = 1.0
		active = 0.0

	for name, val in [('pulse_active', active), ('pulse_progress', progress)]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
