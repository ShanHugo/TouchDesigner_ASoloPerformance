"""
Script CHOP Callbacks - feeding_state/wearinessState1

Every successful feed now triggers a "recoil" (mouth light shrink/dim +
crack shatter), escalating from a small crack on feed 1 to a huge crack by
feed 3, then holding at max for feed 4+. Separately, once past feed 3 a
"weary" value ramps up (0..1) representing accumulated tension, used to
drive a gathering dark-cloud overlay - which the client can physically
push back by pressing down (reusing press_release's spring value).

Outputs:
  weary          - 0..1, rises once feeding_count > Weariedafterfeed,
                   drives the cloud-gathering effect
  recoil         - 0..1 envelope: spikes on every feed, decays back to 0
                   over Recoilduration seconds
  recoil_scale   - 0..1, how big THIS feed's recoil/crack should be:
                   feed 1 -> ~0.33, feed 2 -> ~0.67, feed 3+ -> 1.0 (capped)

me - this DAT
scriptOp - the OP which is cooking
"""

LINETRACK_PATH = '/project1/scene_director/lineTrack1'
STATE_PATH = '/project1/care_second_state/feeding_state/feedingState1'
PRESS_PATH = '/project1/care_second_state/press_release/pressState1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (1,)  # Act 2 only - matches feedingState1's own gate;
                              # once Act 2 ends the weariness/cloud/table state
                              # freezes rather than continuing to compute for
                              # a scene nobody can see
ESCALATE_FEEDS = 3.0  # feed count at which recoil/crack size hits max


_state = {
	'was_active': False,
	'relief_line_at': None,
	'prev_triggered': False,
	'prev_count': None,
	'recoil_start': None,
	'recoil_scale': 0.0,
	'recoil_count': 0,
	'relief': 0.0,
	'last_time': None,
	'table_transform_start': None,
	'table_transformed': False,
	'weary_smooth': 0.0,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Weariness')
	p = page.appendFloat('Weariedafterfeed', label='Feeds Before Clouds Start Gathering')
	p[0].default = 3
	p[0].val = 3
	p[0].normMin = 1
	p[0].normMax = 10
	p = page.appendFloat('Recoilduration', label='Recoil Recovery Time (s)')
	p[0].default = 2.5
	p[0].val = 2.5
	p = page.appendMenu('Reliefmode', label='What Clears The Clouds')
	p[0].menuNames = ['both', 'line', 'gesture']
	p[0].menuLabels = ['Press or the last line', 'Last line only', 'Press only (original)']
	p[0].default = 'both'
	p[0].val = 'both'
	p = page.appendInt('Reliefonline', label='Act 2 Line That Releases')
	p[0].default = 4
	p[0].val = 4
	p[0].normMin = 1
	p[0].normMax = 4
	p = page.appendFloat('Relieflinedelay', label='Delay After That Line Starts (s)')
	p[0].default = 0.0
	p[0].val = 0.0
	p[0].normMin = 0.0
	p[0].normMax = 20.0
	p = page.appendFloat('Linereliefseconds', label='Seconds To Fully Clear On That Line')
	p[0].default = 6.0
	p[0].val = 6.0
	p[0].normMin = 0.5
	p[0].normMax = 20.0
	p = page.appendFloat('Burstholdseconds', label='Hold The Outburst Before Pressing Can Clear It (s)')
	p[0].default = 8.0
	p[0].val = 8.0
	p[0].normMin = 0.0
	p[0].normMax = 30.0
	p = page.appendFloat('Reliefrate', label='Cloud Relief Rate (per second held down)')
	p[0].default = 0.35
	p[0].val = 0.35
	p = page.appendFloat('Tabletransformtime', label='Table Reform Duration (s)')
	p[0].default = 3.0
	p[0].val = 3.0
	p = page.appendFloat('Cloudgatherseconds', label='Cloud Gather-In Duration (s)')
	p[0].default = 3.0
	p[0].val = 3.0
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	sw = op(SWITCH_PATH)
	is_active_scene = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if is_active_scene and not _state['was_active']:
		# entering Act 2: clouds, relief, recoil and the table transform start fresh
		_state.update({
			'prev_triggered': False, 'prev_count': None, 'recoil_start': None, 'recoil_scale': 0.0,
			'recoil_count': 0, 'relief': 0.0, 'last_time': None, 'burst_time': None, 'relief_line_at': None,
			'table_transform_start': None, 'table_transformed': False, 'weary_smooth': 0.0,
		})
		for key in ('weary_cached', 'last_weary', 'last_weary_effective', 'last_cloud_alpha', 'last_table_transform'):
			scriptOp.store(key, 0.0)
	_state['was_active'] = is_active_scene
	if not is_active_scene:
		# frozen: hold last computed state, no further ticking/easing once
		# Act 2 is no longer on screen
		for name, val in [
			('weary', scriptOp.fetch('last_weary', 0.0)),
			('weary_effective', scriptOp.fetch('last_weary_effective', 0.0)),
			('cloud_alpha', scriptOp.fetch('last_cloud_alpha', 0.0)),
			('relief', _state['relief']),
			('recoil', 0.0),
			('recoil_scale', _state['recoil_scale']),
			('table_transform', 1.0 if _state['table_transformed'] else scriptOp.fetch('last_table_transform', 0.0)),
		]:
			chan = scriptOp.appendChan(name)
			chan[0] = val
		return

	now = absTime.seconds
	weary = 0.0
	recoil = 0.0

	try:
		state = op(STATE_PATH)
		if state is not None:
			# cook dependency loop with feedingState1: the CHANNEL can be None
			# mid-frame, which used to kill this whole block silently in the
			# except below (weary stayed 0 and no crack was ever produced).
			feeding_count = state.fetch('feed_count_pub', None)
			if feeding_count is None:
				cnt_chan = state['feeding_count']
				feeding_count = cnt_chan.eval() if cnt_chan is not None else (_state.get('prev_count') or 0.0)
			trig_chan = state['feeding_triggered']
			triggered = (trig_chan.eval() > 0.5) if trig_chan is not None else False

			threshold = scriptOp.par.Weariedafterfeed.eval()
			# hard on/off: as soon as the Nth feed lands (>=, not >, so the
			# par's "Feeds Before Clouds Start Gathering = 3" really means the
			# 3rd feed itself flips it), the cloud/press-down mechanic is fully
			# live - no gradual ramp
			# feedingState1 also publishes burst_pub, set when Act 2 reaches the line
			# 「我真的受不了了！」 - that line is the picture of this moment, so it can
			# raise the clouds on its own even if the feeds never landed.
			line_burst = state.fetch('burst_pub', 0.0) > 0.5
			# Burstmode on feedingState1 is the single source of truth for what
			# raises the outburst. Set to 'line', the feed count must not raise
			# the clouds by itself - one extra feed did it during line 2, and the
			# whole outburst had come and gone before the line it belongs to.
			_bmode = str(state.par.Burstmode.eval()) if hasattr(state.par, 'Burstmode') else 'feed'
			feed_may_burst = _bmode in ('feed', 'both')
			weary = 1.0 if ((feed_may_burst and feeding_count >= threshold) or line_burst) else 0.0

			# feeding_triggered is a ONE-FRAME pulse and this node has no cook-order
			# dependency on feedingState1, so reading it directly misses most feeds
			# (23 feeds produced only 4 recoils in a live test). feeding_count only
			# ever climbs, so an edge on it can never be missed.
			prev_count = _state.get('prev_count')
			count_rose = prev_count is not None and feeding_count > prev_count
			if count_rose or (triggered and not _state['prev_triggered']):
				_state['recoil_start'] = now
				_state['recoil_count'] += 1
				_state['recoil_scale'] = max(0.0, min(1.0, feeding_count / ESCALATE_FEEDS))
			_state['prev_triggered'] = triggered
			_state['prev_count'] = feeding_count
	except Exception as e:
		scriptOp.store('last_error', str(e))

	scriptOp.store('weary_cached', weary)

	if _state['recoil_start'] is not None:
		dt = now - _state['recoil_start']
		dur = max(0.2, scriptOp.par.Recoilduration.eval())
		if dt < dur:
			# sharp onset, slow ease back down - a flinch, not a smooth pulse
			recoil = (max(0.0, 1.0 - (dt / dur)) ** 1.6) * _state['recoil_scale']

	# permanently relieve cloud density while pressing down - unlike the
	# momentary spring bounce, this doesn't come back once released
	dt = 0.0 if _state['last_time'] is None else max(0.0, now - _state['last_time'])
	_state['last_time'] = now

	# ease weariness in for the cloud VISUAL specifically (not the other
	# instant cues like ECG/lights/armed/press-arming) so the cloud mass
	# gathers in gradually instead of snapping to full density the instant
	# the feed threshold is crossed - a linear ramp that reaches the target
	# in exactly Cloudgatherseconds seconds
	gather = max(0.2, scriptOp.par.Cloudgatherseconds.eval())
	max_step = dt / gather
	smooth_diff = weary - _state['weary_smooth']
	if abs(smooth_diff) <= max_step:
		_state['weary_smooth'] = weary
	else:
		_state['weary_smooth'] += max_step if smooth_diff > 0 else -max_step

	try:
		press = op(PRESS_PATH)
		press_depth = press.fetch('press_depth_cached', 0.0) if press is not None else 0.0
	except Exception as e:
		press_depth = 0.0
		scriptOp.store('last_error', str(e))
	# relief is cloud DISPERSAL, so it must not accumulate before there are any
	# clouds: the natural motion of lowering the hand after each feed reads as a
	# press, and with the post-feed arm window that pushed relief to 1.0 before
	# the 3rd feed ever flipped weary on - the clouds were cancelled the instant
	# they were supposed to appear.
	# the outburst has to be READABLE before anyone can cancel it: the crack and
	# the clouds arrive with the 3rd feed, and relief used to be free to start
	# eating them the same second. Nothing disperses for Burstholdseconds after
	# the clouds first appear.
	if weary > 0.0 and _state.get('burst_time') is None:
		_state['burst_time'] = now
	hold_s = scriptOp.par.Burstholdseconds.eval() if hasattr(scriptOp.par, 'Burstholdseconds') else 0.0
	burst_held = _state.get('burst_time') is not None and (now - _state['burst_time']) < hold_s
	# Reliefmode gates BOTH paths. It used to gate only the line, so with the
	# mode set to 'line' the press path still ran every frame: any press the
	# camera read - including the visitor simply standing with their hands low -
	# ate the outburst a little at a time. Measured at 0.014/s with nobody
	# pressing on purpose, which is half the outburst gone over the 37 seconds
	# of 「我真的受不了了！」, the one line it is supposed to hold through.
	mode = str(scriptOp.par.Reliefmode.eval()) if hasattr(scriptOp.par, 'Reliefmode') else 'gesture'
	if weary > 0.0 and not burst_held and mode in ('gesture', 'both'):
		_state['relief'] = max(0.0, min(1.0, _state['relief'] + press_depth * scriptOp.par.Reliefrate.eval() * dt))

	# The visitor is watching Unity, so the press-down that clears the clouds may
	# never reach TD's camera. The last line of Act 2 releases it anyway, so the
	# audience always sees the clouds disperse before the act ends.
	if weary > 0.0 and not burst_held and mode in ('line', 'both'):
		lt = op(LINETRACK_PATH)
		act_ch = lt['td_act'] if lt is not None else None
		line_ch = lt['td_line'] if lt is not None else None
		act = int(round(act_ch.eval())) if act_ch is not None else 0
		line = int(round(line_ch.eval())) if line_ch is not None else 0
		if act == 2 and line >= int(scriptOp.par.Reliefonline.eval()):
			if _state['relief_line_at'] is None:
				_state['relief_line_at'] = now
			if (now - _state['relief_line_at']) >= scriptOp.par.Relieflinedelay.eval():
				dur = max(0.1, scriptOp.par.Linereliefseconds.eval())
				_state['relief'] = max(0.0, min(1.0, _state['relief'] + dt / dur))
		else:
			_state['relief_line_at'] = None
	weary_effective = max(0.0, weary - _state['relief'])
	cloud_alpha = max(0.0, min(1.0, _state['weary_smooth'] - _state['relief']))

	# once the clouds have been substantially dispersed through pressing,
	# the table shatters and reforms into a long table - a one-way,
	# one-time transformation
	if weary > 0.3 and weary_effective < 0.08 and not _state['table_transformed']:
		if _state['table_transform_start'] is None:
			_state['table_transform_start'] = now
	elif weary_effective >= 0.08:
		_state['table_transform_start'] = None  # clouds came back before it finished

	table_transform = 0.0
	if _state['table_transformed']:
		table_transform = 1.0
	elif _state['table_transform_start'] is not None:
		tdur = max(0.2, scriptOp.par.Tabletransformtime.eval())
		tdt = now - _state['table_transform_start']
		table_transform = max(0.0, min(1.0, tdt / tdur))
		if table_transform >= 1.0:
			_state['table_transformed'] = True

	scriptOp.store('last_weary', weary)
	scriptOp.store('last_weary_effective', weary_effective)
	scriptOp.store('last_cloud_alpha', cloud_alpha)
	scriptOp.store('last_table_transform', table_transform)

	for name, val in [
		('weary', weary),
		('weary_effective', weary_effective),
		('cloud_alpha', cloud_alpha),
		('relief', _state['relief']),
		('recoil', recoil),
		('recoil_scale', _state['recoil_scale']),
		('table_transform', table_transform),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
