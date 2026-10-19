"""
Rehearsal panel for scene_director (Rehearsal page).

Manualoverride pins which act is shown AND, since lineTrack1 now reads it, which
act's lines are used; Manuallines pins the line itself. The pulses below reach
into the same state the real gestures / Unity would set, so the piece can be
stepped through by hand with nobody in front of the camera.

me - this DAT
"""

FEED = '/project1/care_second_state/feeding_state/feedingState1_callbacks'
WEARY = '/project1/care_second_state/feeding_state/wearinessState1_callbacks1'
CRACK = '/project1/care_second_state/feeding_visual/crackDraw1_callbacks'
SPLIT = '/project1/care_first_state/ceremony_light/rippleTrigger1_callbacks'
CARD = '/project1/care_third_state/card_sense/cardLockState1_callbacks'
EMBRACE = '/project1/care_third_state/embrace_sense/embraceState1_callbacks1'
BRANCH = '/project1/care_third_state/card_sense/cardBranch1'

LINES_PER_ACT = {1: 3, 2: 4, 3: 3}
SD = '/project1/scene_director'
LINETRACK = '/project1/scene_director/lineTrack1'
LINETRACK_CB = '/project1/scene_director/lineTrack1_callbacks'


def _mod(path):
	d = op(path)
	return d.module if d is not None else None


def _feed(delta=None, reset=False):
	m = _mod(FEED)
	if m is None:
		return
	if reset:
		m._state['feeding_count'] = 0
		m._state['feeding_warmth'] = 0.0
	elif delta:
		m._state['feeding_count'] = max(0, int(m._state['feeding_count']) + delta)
		fo = op('/project1/care_second_state/feeding_state/feedingState1')
		gain = fo.par.Warmthperfeed.eval() if hasattr(fo.par, 'Warmthperfeed') else 0.08
		m._state['feeding_warmth'] = min(1.0, max(0.0, m._state['feeding_warmth'] + gain * delta))


def _release(value=1.0):
	m = _mod(WEARY)
	if m is not None:
		m._state['relief'] = value
		if value <= 0.0:
			m._state['burst_time'] = None


def _split(open_it):
	m = _mod(SPLIT)
	if m is None:
		return
	m._state['anim_start_value'] = m._state['anim_value']
	m._state['anim_target'] = 1.0 if open_it else 0.0
	m._state['anim_start_time'] = absTime.seconds
	# the subtitle branch owns 'line_split_open': leaving it False after a manual
	# OPEN keeps that branch from closing it, and setting it True after a manual
	# CLOSE keeps the branch from immediately re-opening when the line is already
	# past Splitonline. Inverted, hence the look of it.
	m._state['line_split_open'] = not bool(open_it)


def _card(lock):
	m = _mod(CARD)
	if m is None:
		return
	m._state['locked'] = bool(lock)
	m._state['lock_start'] = absTime.seconds if lock else None
	if not lock:
		m._state['line_started_at'] = None


def _embrace():
	m = _mod(EMBRACE)
	if m is not None:
		m._state['embraced'] = True
		m._state['embraced_at'] = absTime.seconds


def _reset_all():
	# feedingState1 FREEZES itself while weariness is latched high, and its frozen
	# branch never rewrites feed_count_pub - the very value wearinessState1 reads to
	# decide it is weary. Clearing the count alone therefore deadlocked the two: the
	# channel read 0 while the storage still read 5, so the clouds never lifted and
	# Unity's live count could not take over. Routing both nodes through their own
	# act-entry branch is the only path that clears every latch, so do that first.
	for _p in (FEED, WEARY):
		_m = _mod(_p)
		if _m is not None:
			_m._state['was_active'] = False
	_fo = op('/project1/care_second_state/feeding_state/feedingState1')
	if _fo is not None:
		_fo.store('feed_count_pub', 0.0)
		_fo.store('feed_trigger_pub', 0.0)
	_wo = op('/project1/care_second_state/feeding_state/wearinessState1')
	if _wo is not None:
		_wo.store('weary_cached', 0.0)
	# Act 3's card branch is part of 'every act state': a rehearsal reset puts the
	# candle back to its pre-draw colour and clears the Manualcard menu with it.
	b = op(BRANCH)
	if b is not None:
		b.par.Resetcard.pulse()
	if hasattr(op('/project1/scene_director').par, 'Manualcard'):
		op('/project1/scene_director').par.Manualcard = 'none'
	_feed(reset=True)
	_release(0.0)
	_split(False)
	_card(False)
	m = _mod(EMBRACE)
	if m is not None:
		m._state['embraced'] = False
		m._state['embraced_at'] = None
		m._state['hold_start'] = None
	c = _mod(CRACK)
	if c is not None:
		c._state['segments'] = []
		c._state['speckles'] = []
		c._state['hit_count'] = 0
		c._state['mask'] = None
	# ...and put the act we are in back to its own start, so "reset everything"
	# really is "run this act again from the top". Without this the state
	# machines cleared but every time-driven cue (Act 1's reveal and bloom, and
	# so the cross's brightness) stayed wherever the clock had got to.
	sd = op(SD)
	if sd is not None:
		if sd.par.Manualoverride.eval():
			_seek_scene_start(sd.par.Manualscene.eval())
		else:
			lt = op(LINETRACK)
			act = int(round(lt['td_act'].eval())) if (lt is not None and lt['td_act'] is not None) else 0
			if 1 <= act <= 3:
				_seek_scene_start('scene%d' % act)


def _step_line(delta):
	sd = op('/project1/scene_director')
	act = int(round(op('/project1/scene_director/lineTrack1')['td_act'].eval()))
	n = LINES_PER_ACT.get(act, 1)
	if not sd.par.Manuallines.eval():
		sd.par.Manuallines = True
		sd.par.Manualline = int(round(op('/project1/scene_director/lineTrack1')['td_line'].eval()))
	sd.par.Manualline = max(1, min(n, int(sd.par.Manualline.eval()) + delta))


def onPulse(par):
	n = par.name
	if n == 'Feedplus':
		_feed(delta=1)
	elif n == 'Feedreset':
		_feed(reset=True)
	elif n == 'Forcerelease':
		_release(1.0)
	elif n == 'Splitopen':
		_split(True)
	elif n == 'Splitclose':
		_split(False)
	elif n == 'Cardlock':
		_card(True)
	elif n == 'Cardunlock':
		_card(False)
	elif n == 'Embracenow':
		_embrace()
	elif n == 'Resetall':
		_reset_all()
	elif n == 'Nextline':
		_step_line(1)
	elif n == 'Prevline':
		_step_line(-1)
	return


def _seek_scene_start(scene_name):
	"""Picking an act by hand puts that act's timer back to 0.

	Manualoverride only pins WHICH act is shown; sceneTimer1 keeps running, so
	the act inherited whatever elapsed the timeline happened to be at. Every
	time-driven cue then started mid-way - picking Act 1 late in a run handed
	s1_targets a progress of ~1, which is why the cross came up at full
	brightness instead of rising through the act."""
	try:
		act = int(str(scene_name).replace('scene', ''))
	except Exception:
		return
	if act < 1 or act > 3:
		return
	lt = op(LINETRACK)
	mod = _mod(LINETRACK_CB)
	sd = op(SD)
	if lt is None or mod is None or sd is None:
		return
	line = 1
	if sd.par.Manuallines.eval():
		line = max(1, min(LINES_PER_ACT[act], int(sd.par.Manualline.eval())))
	mod._seek_timeline_to(act, line, lt, nudge=False)


def onValueChange(par, prev):
	sd = op(SD)
	if sd is None:
		return
	# only the act picker moves the clock; stepping lines by hand leaves it alone
	if par.name == 'Manualscene' and sd.par.Manualoverride.eval():
		_seek_scene_start(par.eval())
	elif par.name == 'Manualoverride' and par.eval():
		_seek_scene_start(sd.par.Manualscene.eval())
	return
