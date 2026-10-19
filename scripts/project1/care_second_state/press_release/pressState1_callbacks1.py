"""
Script CHOP Callbacks - press_release/pressState1

Second-stage gesture after a successful feed: for a short window after
feeding_triggered fires, both hands pressing down (average hand height
dropping) compresses a spring-driven overall-intensity target. Releasing
(hands lifted, or the window simply expiring) lets the target return to
baseline, and the downstream Spring CHOP turns that step back into a
damped bounce.

Outputs:
  armed          - 1.0 while the post-feed press window is open
  press_depth    - 0..1, how far the hands are pressed down (0=resting, 1=fully pressed)
  press_target   - fed into the Spring CHOP: 1.0 baseline, dips toward
                    Mindip as press_depth increases

me - this DAT
scriptOp - the OP which is cooking
"""

FEED_PATH = '/project1/care_second_state/feeding_state/feedingState1'
WEARY_PATH = '/project1/care_second_state/feeding_state/wearinessState1'
HANDPOSE_PATH = '/project1/care_first_state/hand_pose_detection/handPose1'

_state = {'armed_until': -1.0, 'zone_entered_at': None, 'prev_count': None}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('PressRelease')
	p = page.appendFloat('Armwindow', label='Arm Window After Feed (s)')
	p[0].default = 4.0
	p[0].val = 4.0
	p = page.appendFloat('Presstop', label='Press Start Y (above = not pressing)')
	p[0].default = 0.6
	p[0].val = 0.6
	p = page.appendFloat('Pressbottom', label='Press Full Y (at/below = fully pressed)')
	p[0].default = 0.32
	p[0].val = 0.32
	p = page.appendFloat('Mindip', label='Min Target At Full Press')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0
	p[0].normMax = 1
	p = page.appendFloat('Presswindowseconds', label='Look-back Window For Downward Motion (s)')
	p[0].default = 1.2
	p[0].val = 1.2
	p[0].normMin = 0.2
	p[0].normMax = 3.0
	p = page.appendFloat('Pressdropmin', label='Min Downward Drop To Count As A Press')
	p[0].default = 0.06
	p[0].val = 0.06
	p[0].normMin = 0.0
	p[0].normMax = 0.3
	p = page.appendFloat('Holdconfirmseconds', label='Hold In Zone To Confirm Press (s)')
	p[0].default = 0.25
	p[0].val = 0.25
	p[0].normMin = 0
	p[0].normMax = 1.5
	return


def onPulse(par):
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	now = absTime.seconds
	armed = 0.0
	press_depth = 0.0

	try:
		feed = op(FEED_PATH)
		if feed is not None:
			# same one-frame-pulse race as wearinessState1: the monotonic feed
			# counter is the edge that cannot be missed
			fc = feed.fetch('feed_count_pub', None)
			if fc is None:
				fc_chan = feed['feeding_count']
				fc = fc_chan.eval() if fc_chan is not None else (_state.get('prev_count') or 0.0)
			prev_count = _state.get('prev_count')
			if (prev_count is not None and fc > prev_count) or feed.fetch('feed_trigger_pub', 0.0) > 0.5:
				_state['armed_until'] = now + scriptOp.par.Armwindow.eval()
			_state['prev_count'] = fc

		# armed either briefly after a feed (original climax gesture), or
		# continuously once the clouds have started gathering - pressing down
		# should be able to push the clouds back at any time, not just in a
		# narrow window right after feeding
		weary_op = op(WEARY_PATH)
		weary = weary_op.fetch('weary_cached', 0.0) if weary_op is not None else 0.0
		hp_now = op(HANDPOSE_PATH)
		if hp_now is None or hp_now['hands_present'].eval() <= 0.5:
			_state['y_hist'] = []
			_state['press_active'] = False
		if now < _state['armed_until'] or weary > 0.0:
			armed = 1.0
			hp = op(HANDPOSE_PATH)
			raw_press_depth = 0.0
			if hp is not None and hp['hands_present'].eval() > 0.5:
				y = hp['pose_y'].eval()
				top = scriptOp.par.Presstop.eval()
				bottom = scriptOp.par.Pressbottom.eval()
				raw_press_depth = max(0.0, min(1.0, (top - y) / max(1e-4, top - bottom)))

			# require the hand to have been continuously inside the press
			# zone for a short moment before it counts - filters out just
			# passing through the zone as the tail end of some other
			# gesture (e.g. lowering hands after feeding) from accidentally
			# registering as a deliberate press
			# a press is a MOVEMENT, not a height. Reading only the hand's height
			# meant a hand resting anywhere below Presstop scored a full press:
			# relief ran to 1.0 on its own and cancelled the burst (heat fell to
			# Presscooled and the crack faded) seconds after the 3rd feed, with
			# nobody pressing anything. The hand now has to have come DOWN by
			# Pressdropmin within Presswindowseconds to start a press; once
			# started it stays active while the hand remains in the zone, so
			# holding it down still keeps clearing the clouds.
			hist = _state.setdefault('y_hist', [])
			hist.append((now, y))
			win = max(0.05, scriptOp.par.Presswindowseconds.eval())
			while hist and (now - hist[0][0]) > win:
				hist.pop(0)
			drop = (max(v for _, v in hist) - y) if hist else 0.0
			moved_down = drop >= scriptOp.par.Pressdropmin.eval()

			in_zone = raw_press_depth > 0.12
			if in_zone:
				if _state['zone_entered_at'] is None:
					_state['zone_entered_at'] = now
			else:
				_state['zone_entered_at'] = None
				_state['press_active'] = False

			hold_needed = scriptOp.par.Holdconfirmseconds.eval()
			if (in_zone and moved_down and _state['zone_entered_at'] is not None
					and (now - _state['zone_entered_at']) >= hold_needed):
				_state['press_active'] = True
			if in_zone and _state.get('press_active'):
				press_depth = raw_press_depth
	except Exception as e:
		scriptOp.store('last_error', str(e))

	mindip = scriptOp.par.Mindip.eval()
	press_target = 1.0 - press_depth * (1.0 - mindip)

	scriptOp.store('press_depth_cached', press_depth)

	for name, val in [('armed', armed), ('press_depth', press_depth), ('press_target', press_target)]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
