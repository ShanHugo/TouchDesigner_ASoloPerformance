"""
Script CHOP Callbacks - embrace_sense/embraceState1

Final action of Act 3: the caregiver embraces themself (arms crossed onto
opposite shoulders), held for a sustained duration, closing the piece.
Reuses Act 1's chest_alignment/poseTrack1 pose instance (self_hug_score)
rather than spinning up another MediaPipe detector.

Outputs:
  self_hug_score  - live passthrough of poseTrack1's self-hug closeness score
  held_seconds    - how long the self-hug has been continuously sustained
  embraced        - 1.0 once the hold duration is reached; latches on and
                     stays 1.0 (the ending does not undo itself) until
                     Resetembrace is pulsed

me - this DAT
scriptOp - the OP which is cooking
"""

POSE_PATH = '/project1/care_third_state/embrace_sense/selectPose1'
CARDLOCK_PATH = '/project1/care_third_state/card_sense/cardLockState1'
PHASE_PATH = '/project1/care_third_state/card_sense/act3PhaseState1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (2,)  # Act 3 only - see gate note in onCook

_state = {'was_active': False, 'hold_start': None, 'embraced': False, 'embraced_at': None}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('EmbraceState')
	p = page.appendFloat('Holdseconds', label='Hold Duration To Confirm (s)')
	p[0].default = 2.0
	p[0].val = 2.0
	p = page.appendFloat('Selfhugthreshold', label='Self-Hug Score Threshold')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	p = page.appendFloat('Autoresetseconds', label='Auto-Reset After Embrace (s, 0=off)')
	p[0].default = 10.0
	p[0].val = 10.0
	p = page.appendPulse('Resetembrace', label='Reset Embrace Ending')
	return


def onPulse(par):
	if par.name == 'Resetembrace':
		_state['hold_start'] = None
		_state['embraced'] = False
		_state['embraced_at'] = None
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	now = absTime.seconds
	score = 0.0
	held = 0.0

	# gate: poseTrack1 also runs in Act 1, and the card lock used to leak in from
	# Act 2 - the ending may only be reached inside Act 3
	sw = op(SWITCH_PATH)
	active = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if active and not _state['was_active']:
		_state['hold_start'] = None
		_state['embraced'] = False
		_state['embraced_at'] = None
	_state['was_active'] = active

	try:
		pose = op(POSE_PATH) if active else None
		cardlock = op(CARDLOCK_PATH)
		# the self-hug ending only becomes reachable once the card has been
		# placed and settled into its slot - it's the release that follows
		# the ritual, not a separate unrelated gesture check
		# reachable only once the card light has landed in the chest and the scar
		# is surfacing - hugging earlier would pour gold into a crack nobody can see yet
		ph = op(PHASE_PATH)
		if ph is not None:
			card_locked = ph['landed'].eval() > 0.5
		else:
			card_locked = cardlock['locked'].eval() > 0.5 if cardlock is not None else True
		if pose is not None:
			score = pose['self_hug_score'].eval()
			pose_found = pose['pose_found'].eval()
			threshold = scriptOp.par.Selfhugthreshold.eval()

			if card_locked and pose_found > 0.5 and score >= threshold:
				if _state['hold_start'] is None:
					_state['hold_start'] = now
				held = now - _state['hold_start']
			else:
				_state['hold_start'] = None
				held = 0.0

			if held >= scriptOp.par.Holdseconds.eval() and not _state['embraced']:
				_state['embraced'] = True
				_state['embraced_at'] = now
	except Exception as e:
		scriptOp.store('last_error', str(e))

	auto_reset = scriptOp.par.Autoresetseconds.eval()
	if _state['embraced'] and _state['embraced_at'] is not None and auto_reset > 0:
		if now - _state['embraced_at'] >= auto_reset:
			_state['hold_start'] = None
			_state['embraced'] = False
			_state['embraced_at'] = None

	for name, val in [
		('self_hug_score', score),
		('held_seconds', held),
		('embraced', 1.0 if _state['embraced'] else 0.0),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
