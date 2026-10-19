"""
Script CHOP Callbacks - feeding_state/feedingState1

Sequential gate for the "bowl then mouth" feeding gesture:
  1. hand must be in the bowl zone AND actively pinch/grab (thumb-index)
     to pick up the light - sets a "carrying" flag
  2. only then does entering the mouth zone register as a feeding action
  3. touching mouth without having touched bowl first does nothing (quiet,
     no penalty - matches the project's quiet/fragile tone)
  4. after a successful feed, the carrying flag resets, so the next feed
     needs a fresh scoop
  5. if bowl is touched but mouth is never reached, the carrying flag times
     out and resets on its own (avoids a stale "still carrying" state)

Outputs:
  carrying           - 1.0 while bowl has been touched and mouth not yet reached
  feeding_triggered  - 1.0 for one frame when a feed completes
  feeding_count      - total number of completed feeds this run
  feeding_warmth     - cumulative 0..1 warmth, permanently nudged up per feed,
                        never resets on its own (persists across the whole scene)

me - this DAT
scriptOp - the OP which is cooking
"""

BOWL_PATH = '/project1/care_second_state/bowl_zone/bowlOut1'
MOUTH_PATH = '/project1/care_second_state/mouth_zone/mouthOut1'
HAND_PATH = '/project1/care_second_state/bowl_zone/handGrab1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (1,)  # Act 2 only - handGrab1 stays live through Act 3
                              # (reused for card-draw), so without this gate a
                              # grab near the old bowl/mouth screen coordinates
                              # during Act 3 could silently register as a feed
                              # even though the bowl/mouth visuals are long gone
WEARY_PATH = '/project1/care_second_state/feeding_state/wearinessState1'
LINETRACK_PATH = '/project1/scene_director/lineTrack1'
EFFECTCTRL_PATH = '/project1/effect_controller/effectController1'
OSC_PATH = '/project1/scene_director/oscInFromUnity1'
OSCSYNC_PATH = '/project1/scene_director/oscSync1'
# The visitor wears the Unity side and never sees TD - TD is for the audience
# outside. So when Unity reports its own feed count (cumulative /FeedCount,
# sent every frame, reset to 0 per visitor), that count is the truth and TD
# mirrors it: a dropped UDP packet is simply corrected by the next frame.
# The camera gesture then only drives the 'carrying' visual. Without a live
# Unity (or before Unity sends the channel) TD falls back to the camera.
# bowlMarker1/mouthLight1's fillalpha both multiply by (1.0 - weary), so once
# weary kicks in (feeding_count > Weariedafterfeed) the light points go fully
# transparent - invisible. Feeding must stop registering at that same moment,
# otherwise the gesture keeps working against a target nobody can see.

_state = {
	'was_active': False,
	'carrying': False,
	'await_leave': False,
	'carrying_since': None,
	'feeding_count': 0,
	'feeding_warmth': 0.0,
	'feed_source': 0.0,
	'line_burst': False,
	'line_burst_at': None,
	'unity_armed': False,
}


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('FeedingState')
	p = page.appendFloat('Carrytimeout', label='Carry Timeout (s, resets if mouth not reached)')
	p[0].default = 8.0
	p[0].val = 8.0
	p = page.appendFloat('Warmthperfeed', label='Warmth Gained Per Feed')
	p[0].default = 0.08
	p[0].val = 0.08
	p[0].normMin = 0
	p[0].normMax = 0.5
	p = page.appendPulse('Resetfeeding', label='Reset Feeding Progress')
	page = scriptOp.appendCustomPage('FollowUnity')
	p = page.appendMenu('Burstmode', label='What Floods The Screen Red')
	p[0].menuNames = ['both', 'feed', 'line']
	p[0].menuLabels = ['Either the feeds or the line', 'Feed count only', 'Subtitle line only']
	p[0].default = 'both'
	p[0].val = 'both'
	p = page.appendInt('Burstonline', label='Act 2 Line That Floods The Screen')
	p[0].default = 3
	p[0].val = 3
	p[0].normMin = 1
	p[0].normMax = 4
	p = page.appendFloat('Burstlinedelay', label='Delay After That Line Starts (s)')
	p[0].default = 0.0
	p[0].val = 0.0
	p[0].normMin = 0.0
	p[0].normMax = 20.0
	p = page.appendToggle('Followunityfeed', label='Count Feeds From Unity When Live')
	p[0].default = True
	p[0].val = True
	p = page.appendStr('Unityfeedchannel', label='Unity Feed Count Channel')
	p[0].default = 'FeedCount'
	p[0].val = 'FeedCount'
	return


def _unity_feed_count(scriptOp):
	# Unity's cumulative feed count, or None when TD should use the camera
	try:
		if not scriptOp.par.Followunityfeed.eval():
			return None
		sy = op(OSCSYNC_PATH)
		if sy is None or sy['unity_live'].eval() < 0.5:
			return None
		osc = op(OSC_PATH)
		ch = osc.chan(scriptOp.par.Unityfeedchannel.eval()) if osc is not None else None
		if ch is None:
			return None
		v = max(0, int(round(ch.eval())))
		# Unity's counter is the CURRENT LEVEL's interact count, and for a few frames
		# after Act 2 opens it still holds Act 1's last level (a CheckDetectionArea
		# with 5 areas, so it reads 5) - straight through TD's burst threshold of 3,
		# which flooded the screen red the instant Act 2 began. Wait until it has
		# actually read 0 since entering Act 2 before believing it. Unity has its own
		# arming latch now too; this is the guard for an older Unity build.
		if not _state['unity_armed']:
			if v != 0:
				return None
			_state['unity_armed'] = True
		return v
	except Exception:
		return None


def onPulse(par):
	if par.name == 'Resetfeeding':
		_state['carrying'] = False
		_state['await_leave'] = False
		_state['carrying_since'] = None
		_state['feeding_count'] = 0
		_state['feeding_warmth'] = 0.0
	return


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	sw = op(SWITCH_PATH)
	is_active_scene = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if is_active_scene and not _state['was_active']:
		# entering Act 2: the visitor starts with no feeds. Also clear the cached
		# weariness now, so the stale "lights hidden" value from the previous
		# visitor can't freeze feeding for the first frame.
		_state['carrying'] = False
		_state['await_leave'] = False
		_state['carrying_since'] = None
		_state['feeding_count'] = 0
		_state['feeding_warmth'] = 0.0
		_state['line_burst'] = False
		_state['line_burst_at'] = None
		_state['unity_armed'] = False
		w = op(WEARY_PATH)
		if w is not None:
			w.store('weary_cached', 0.0)
	_state['was_active'] = is_active_scene

	# 「我真的受不了了！」 - the red flood and the cracks ARE the picture of that line,
	# so the line can fire them on its own. Published as a separate flag rather than
	# by inflating feeding_count: that count mirrors Unity's real number of feeds and
	# must not start lying about it (and it also scales the recoil).
	_burst_mode = str(scriptOp.par.Burstmode.eval()) if hasattr(scriptOp.par, 'Burstmode') else 'feed'
	if is_active_scene and _burst_mode in ('line', 'both'):
		_lt = op(LINETRACK_PATH)
		_a = _lt['td_act'] if _lt is not None else None
		_l = _lt['td_line'] if _lt is not None else None
		_act = int(round(_a.eval())) if _a is not None else 0
		_line = int(round(_l.eval())) if _l is not None else 0
		if _act == 2 and _line >= int(scriptOp.par.Burstonline.eval()):
			if _state['line_burst_at'] is None:
				_state['line_burst_at'] = absTime.seconds
			if (absTime.seconds - _state['line_burst_at']) >= scriptOp.par.Burstlinedelay.eval():
				_state['line_burst'] = True      # one-way inside the act, like the other beats
		else:
			_state['line_burst_at'] = None
	# only ever TRUE inside Act 2: the latch is cleared on act entry, so without
	# this gate it stayed published across Act 1 and Act 3 from the previous run
	_burst_now = bool(is_active_scene and _state['line_burst'])
	scriptOp.store('burst_pub', 1.0 if _burst_now else 0.0)

	weary_op = op(WEARY_PATH)
	weary_cached = weary_op.fetch('weary_cached', 0.0) if weary_op is not None else 0.0
	light_hidden = weary_cached >= 0.5

	if not is_active_scene or light_hidden:
		# frozen: hold the last state, don't read gestures or change anything -
		# once Act 2 is over, feeding can never be triggered again
		for name, val in [
			('carrying', 1.0 if _state['carrying'] else 0.0),
			('feeding_triggered', 0.0),
			('feeding_count', float(_state['feeding_count'])),
			('feeding_warmth', _state['feeding_warmth']),
			('feed_source', _state['feed_source']),
			('burst_line', 1.0 if _burst_now else 0.0),
		]:
			chan = scriptOp.appendChan(name)
			chan[0] = val
		return

	feeding_triggered = 0.0
	now = absTime.seconds
	unity_count = _unity_feed_count(scriptOp)
	_state['feed_source'] = 1.0 if unity_count is not None else 0.0

	try:
		bowl = op(BOWL_PATH)
		mouth = op(MOUTH_PATH)
		hand = op(HAND_PATH)

		hands_present = hand['hand_active'].eval() if hand is not None else 0.0
		grab_active = hand['grab_active'].eval() if hand is not None else 0.0
		bowl_distance = bowl['bowl_distance'].eval() if bowl is not None else 999.0
		mouth_distance = mouth['mouth_distance'].eval() if mouth is not None else 999.0

		bowl_radius = op('/project1/care_second_state/bowl_zone').par.Bowlradius.eval()
		mouth_radius = op('/project1/care_second_state/mouth_zone').par.Mouthradius.eval()

		if hands_present > 0.5:
			bowl_touched = (bowl_distance < bowl_radius) and (grab_active > 0.5)
			mouth_reached = mouth_distance < mouth_radius

			# the bowl zone (chest + Bowlyoffset) and the mouth zone can overlap on
			# screen, so a hand sitting inside BOTH used to flip carry->feed->carry
			# every other frame: one gesture scored 3 feeds in 0.05s (and 23 in an
			# earlier run). the hand has to leave the mouth zone before the next
			# feed can count, which is what the real gesture does anyway.
			if not mouth_reached:
				_state['await_leave'] = False

			if not _state['carrying'] and bowl_touched and not mouth_reached:
				_state['carrying'] = True
				_state['carrying_since'] = now

			elif _state['carrying'] and mouth_reached and not _state.get('await_leave'):
				_state['await_leave'] = True
				if unity_count is None:
					feeding_triggered = 1.0
					_state['feeding_count'] += 1
					gain = scriptOp.par.Warmthperfeed.eval()
					_state['feeding_warmth'] = min(1.0, _state['feeding_warmth'] + gain)
				_state['carrying'] = False
				_state['carrying_since'] = None

		if _state['carrying'] and _state['carrying_since'] is not None:
			timeout = scriptOp.par.Carrytimeout.eval()
			if (now - _state['carrying_since']) > timeout:
				_state['carrying'] = False
				_state['carrying_since'] = None
	except Exception as e:
		scriptOp.store('last_error', str(e))

	if unity_count is not None and unity_count > _state['feeding_count']:
		# never counts down: Unity returning to 0 for the next visitor is
		# handled by this node's own reset on entering Act 2
		gained = unity_count - _state['feeding_count']
		feeding_triggered = 1.0
		_state['feeding_count'] = unity_count
		gain = scriptOp.par.Warmthperfeed.eval() * gained
		_state['feeding_warmth'] = min(1.0, _state['feeding_warmth'] + gain)

	# published to storage as well: wearinessState1/pressState1/feedPulseTrigger1
	# are in a cook dependency loop with this node, so reading these as CHANNELS
	# hands them a None mid-frame. storage has no cook dependency - same trick
	# this node already uses to read weary_cached back from wearinessState1.
	scriptOp.store('feed_count_pub', float(_state['feeding_count']))
	scriptOp.store('feed_trigger_pub', float(feeding_triggered))
	for name, val in [
		('carrying', 1.0 if _state['carrying'] else 0.0),
		('feeding_triggered', feeding_triggered),
		('feeding_count', float(_state['feeding_count'])),
		('feeding_warmth', _state['feeding_warmth']),
		('feed_source', _state['feed_source']),
		('burst_line', 1.0 if _burst_now else 0.0),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
