"""
Script CHOP Callbacks - feeding_visual/carryFlicker1

Fragility tension for carrying the light: the faster the hand moves while
carrying, the more the light flickers/wavers - like it's about to spill.
Slow, careful movement stays steady; fast, careless movement gets unstable.
Per client direction: "不穩定閃爍" (unstable flicker) tied to carry speed,
not a screen-wide darkening effect.

Outputs:
  flicker  - 0..1 multiplier for the carried light's brightness. 1.0 = stable
             (not carrying, or carrying slowly/carefully). Dips and jitters
             as carry speed increases.
  speed    - 0..1 normalized hand speed, for reference/tuning

me - this DAT
scriptOp - the OP which is cooking
"""

import math
import random

HAND_PATH = '/project1/care_second_state/bowl_zone/handGrab1'
STATE_PATH = '/project1/care_second_state/feeding_state/feedingState1'

_state = {'prev_x': 0.5, 'prev_y': 0.5, 'prev_time': None}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('CarryFlicker')
	p = page.appendFloat('Maxspeed', label='Speed At Max Instability (screen-fractions/sec)')
	p[0].default = 1.2
	p[0].val = 1.2
	p[0].normMin = 0.1
	p[0].normMax = 4.0
	p = page.appendFloat('Flickerintensity', label='Flicker Intensity At Max Speed')
	p[0].default = 0.7
	p[0].val = 0.7
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	now = absTime.seconds
	flicker = 1.0
	speed_norm = 0.0

	try:
		hand = op(HAND_PATH)
		state = op(STATE_PATH)
		carrying = state['carrying'].eval() > 0.5 if state is not None else False

		if hand is not None and carrying:
			x = hand['hand_x'].eval()
			y = hand['hand_y'].eval()

			if _state['prev_time'] is not None:
				dt = max(1e-3, now - _state['prev_time'])
				dist = math.sqrt((x - _state['prev_x']) ** 2 + (y - _state['prev_y']) ** 2)
				speed = dist / dt
				max_speed = max(0.05, scriptOp.par.Maxspeed.eval())
				speed_norm = max(0.0, min(1.0, speed / max_speed))

				intensity = scriptOp.par.Flickerintensity.eval()
				jitter = random.uniform(0.4, 1.0)
				flicker = 1.0 - speed_norm * intensity * jitter

			_state['prev_x'] = x
			_state['prev_y'] = y
			_state['prev_time'] = now
		else:
			_state['prev_time'] = None
	except Exception as e:
		scriptOp.store('last_error', str(e))

	for name, val in [('flicker', flicker), ('speed', speed_norm)]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
