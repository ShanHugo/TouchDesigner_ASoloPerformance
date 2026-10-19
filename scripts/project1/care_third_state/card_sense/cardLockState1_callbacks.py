"""
Script CHOP Callbacks - card_sense/cardLockState1

Once the card has been PLACED (released) close enough to the table's card
slot, it locks in permanently - the slot visually fills in and the card
glow stops following the tracked hand/card position entirely, settling
into the slot instead. One-way latch: once locked, stays locked (the
ritual does not undo itself), matching the project's other "ending"
states (embraceState1, table_transform, etc). Resetcardlock un-latches it
for testing.

SLOT_X/SLOT_Y must match card_visual's table slot position (TABLE_CX/
TABLE_CY offset-space constants, converted to 0..1 fraction space).

Outputs:
  locked         - 0/1, latches to 1 once the card has been placed inside
                   Lockradius of the slot
  lock_progress  - 0..1, eases in over Locksmoothseconds once locked -
                   drives the slot fill-in and the glow's snap-to-slot

me - this DAT
scriptOp - the OP which is cooking
"""

import math

CARDSTATE_PATH = '/project1/care_third_state/card_sense/cardState1'
LINETRACK_PATH = '/project1/scene_director/lineTrack1'
SLOT_X = 0.5
SLOT_Y = 0.32
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (2,)  # Act 3 only - see gate note in onCook

_state = {
	'was_active': False,
	'locked': False,
	'lock_start': None,
	'line_started_at': None,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('CardLock')
	p = page.appendMenu('Lockmode', label='What Locks The Card')
	p[0].menuNames = ['line', 'gesture', 'both']
	p[0].menuLabels = ['Subtitle line (reliable)', 'Place gesture (original)', 'Either']
	p[0].default = 'line'
	p[0].val = 'line'
	p = page.appendInt('Lockonline', label='Act 3 Line That Locks The Card')
	p[0].default = 2
	p[0].val = 2
	p[0].normMin = 1
	p[0].normMax = 3
	p = page.appendFloat('Locklinedelay', label='Delay After That Line Starts (s)')
	p[0].default = 3.0
	p[0].val = 3.0
	p[0].normMin = 0.0
	p[0].normMax = 20.0
	p = page.appendFloat('Lockradius', label='Lock-In Radius (fraction of screen)')
	p[0].default = 0.09
	p[0].val = 0.09
	p[0].normMin = 0.02
	p[0].normMax = 0.3
	p = page.appendFloat('Locksmoothseconds', label='Lock-In Ease Duration (s)')
	p[0].default = 0.6
	p[0].val = 0.6
	p[0].normMin = 0.1
	p[0].normMax = 2.0
	p = page.appendFloat('Rippleduration', label='Release Ripple Duration (s)')
	p[0].default = 1.8
	p[0].val = 1.8
	p[0].normMin = 0.3
	p[0].normMax = 4.0
	p = page.appendPulse('Resetcardlock', label='Reset Card Lock')
	return


def onPulse(par):
	if par.name == 'Resetcardlock':
		_state['locked'] = False
		_state['lock_start'] = None
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	now = absTime.seconds

	# gate: only Act 3 may latch the lock (see cardState1's gate note)
	sw = op(SWITCH_PATH)
	active = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if active and not _state['was_active']:
		_state['locked'] = False
		_state['lock_start'] = None
		_state['line_started_at'] = None
	_state['was_active'] = active

	# The visitor is looking at Unity, not at this screen, so the card beat cannot
	# depend on a pinch gesture landing in front of TD's camera: by default the
	# card locks on its line of the Act 3 narration. The gesture still works when
	# Lockmode is gesture/both.
	mode = str(scriptOp.par.Lockmode.eval()) if hasattr(scriptOp.par, 'Lockmode') else 'gesture'
	if active and not _state['locked'] and mode in ('line', 'both'):
		lt = op(LINETRACK_PATH)
		act_ch = lt['td_act'] if lt is not None else None
		line_ch = lt['td_line'] if lt is not None else None
		act = int(round(act_ch.eval())) if act_ch is not None else 0
		line = int(round(line_ch.eval())) if line_ch is not None else 0
		want = int(scriptOp.par.Lockonline.eval())
		if act == 3 and line >= want:
			if _state['line_started_at'] is None:
				_state['line_started_at'] = now
			if (now - _state['line_started_at']) >= scriptOp.par.Locklinedelay.eval():
				_state['locked'] = True
				_state['lock_start'] = now
		else:
			_state['line_started_at'] = None

	try:
		cs = op(CARDSTATE_PATH) if (active and mode in ('gesture', 'both')) else None
		if cs is not None and not _state['locked']:
			placed = cs['placed'].eval() > 0.5
			card_x = cs['card_x'].eval()
			card_y = cs['card_y'].eval()
			dist = math.hypot(card_x - SLOT_X, card_y - SLOT_Y)
			lock_radius = scriptOp.par.Lockradius.eval()
			if placed and dist <= lock_radius:
				_state['locked'] = True
				_state['lock_start'] = now
	except Exception as e:
		scriptOp.store('last_error', str(e))

	lock_progress = 0.0
	if _state['locked']:
		dur = max(0.1, scriptOp.par.Locksmoothseconds.eval())
		lock_progress = max(0.0, min(1.0, (now - _state['lock_start']) / dur)) if _state['lock_start'] is not None else 1.0

	ripple_progress = 1.0
	if _state['locked'] and _state['lock_start'] is not None:
		rdur = max(0.1, scriptOp.par.Rippleduration.eval())
		ripple_progress = max(0.0, min(1.0, (now - _state['lock_start']) / rdur))

	for name, val in [
		('locked', 1.0 if _state['locked'] else 0.0),
		('lock_progress', lock_progress),
		('ripple_progress', ripple_progress),
		('slot_x', SLOT_X),
		('slot_y', SLOT_Y),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
