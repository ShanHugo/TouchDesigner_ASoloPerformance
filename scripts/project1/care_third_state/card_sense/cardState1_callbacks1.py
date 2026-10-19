"""
Script CHOP Callbacks - card_sense/cardState1

First action of Act 3: draw a card and place it on the table.
Reuses Act 2's single-hand pinch/grab detector (bowl_zone/handGrab1) rather
than spinning up another MediaPipe instance, since Act 2 and Act 3 never
run concurrently (scene_director shows one scene at a time).

  1. pinching (grab_active) anywhere picks the card up ("draw") - it
     appears at the hand and follows it, leaving a short draw-streak trail
  2. releasing the pinch "places" the card - it locks at the release
     position and stays there
  3. v1 keeps this simple: no explicit table-zone gate yet, any release
     counts as placing (can add a table-zone gate later once the desk
     layout / next actions are designed)

Outputs:
  carrying  - 1.0 while the card is being actively drawn/held
  placed    - 1.0 once a card has been placed (stays 1 until a new draw starts)
  card_x, card_y - current display position of the card (hand pos while
                    carrying, frozen release pos once placed)

me - this DAT
scriptOp - the OP which is cooking
"""

HAND_PATH = '/project1/care_third_state/card_sense/selectHandGrab1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (2,)  # Act 3 only - see gate note in onCook

_state = {
	'was_active': False,
	'carrying': False,
	'placed': False,
	'card_x': 0.5,
	'card_y': 0.5,
}


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	# gate: handGrab1 is shared with Act 2, where pinching the bowl light (it sits
	# almost exactly over this card slot on screen) used to register as drawing and
	# placing the card - locking Act 3 before Act 3 ever started
	sw = op(SWITCH_PATH)
	active = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if active and not _state['was_active']:
		# entering Act 3: always start from an undrawn card
		_state['carrying'] = False
		_state['placed'] = False
		_state['card_x'] = 0.5
		_state['card_y'] = 0.5
	_state['was_active'] = active
	if not active:
		for name, val in [
			('carrying', 1.0 if _state['carrying'] else 0.0),
			('placed', 1.0 if _state['placed'] else 0.0),
			('card_x', _state['card_x']),
			('card_y', _state['card_y']),
		]:
			chan = scriptOp.appendChan(name)
			chan[0] = val
		return

	try:
		hand = op(HAND_PATH)
		hand_active = hand['hand_active'].eval() if hand is not None else 0.0
		grab_active = hand['grab_active'].eval() if hand is not None else 0.0
		hand_x = hand['hand_x'].eval() if hand is not None else 0.5
		hand_y = hand['hand_y'].eval() if hand is not None else 0.5

		if hand_active > 0.5 and grab_active > 0.5:
			if not _state['carrying']:
				_state['carrying'] = True
				_state['placed'] = False
			_state['card_x'] = hand_x
			_state['card_y'] = hand_y
		elif _state['carrying'] and grab_active < 0.5:
			_state['carrying'] = False
			_state['placed'] = True
	except Exception as e:
		scriptOp.store('last_error', str(e))

	for name, val in [
		('carrying', 1.0 if _state['carrying'] else 0.0),
		('placed', 1.0 if _state['placed'] else 0.0),
		('card_x', _state['card_x']),
		('card_y', _state['card_y']),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
