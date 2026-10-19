"""
Script CHOP Callbacks - card_visual/act3FocusState1

Drives the "focus this moment" effects tied specifically to the very first
line of Act 3 ("請跟著直覺抽一張牌。先不要看文字，只看圖像。") - the
instruction to draw intuitively and look only at the card, per client
request. Once the line advances past line 1, everything eases back off.

Reads lineTrack1 (scene_director) - TD's own time-driven act/line state -
rather than anything gesture-based, so this stays purely a narration-timed
beat like the rest of the script/subtitle system.

Outputs:
  focus          - 0..1, eases toward 1 while Act 3 Line 1 is showing, else
                   eases back to 0 (Focusfadeseconds controls the ease time)
  glow_pulse     - multiplier >=1 for cardGlow1's radius, breathing in/out
                   with a sine while focus>0 (Pulseperiod/Pulseamount)
  vignette_alpha - focus * Vignettestrength, the vignette layer's opacity

me - this OP
scriptOp - the OP which is cooking
"""

import math

LINETRACK_PATH = '/project1/scene_director/lineTrack1'
TARGET_ACT = 3
TARGET_LINE = 1

_state = {
	'focus': 0.0,
	'last_time': None,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Act3Focus')

	def addf(name, label, default, lo, hi):
		p = page.appendFloat(name, label=label)
		p[0].default = default
		p[0].val = default
		p[0].normMin = lo
		p[0].normMax = hi

	addf('Focusfadeseconds', 'Focus Ease In/Out (s)', 0.8, 0.1, 3.0)
	addf('Pulseperiod', 'Glow Pulse Period (s)', 1.6, 0.4, 5.0)
	addf('Pulseamount', 'Glow Pulse Radius Boost (max multiplier - 1)', 0.4, 0.0, 1.5)
	addf('Vignettestrength', 'Vignette Max Darkness (alpha)', 0.65, 0.0, 1.0)
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60
	now = absTime.seconds

	dt = 0.0 if _state['last_time'] is None else max(0.0, now - _state['last_time'])
	_state['last_time'] = now

	lt = op(LINETRACK_PATH)
	on_target = False
	if lt is not None:
		act = int(round(lt['td_act'].eval()))
		line = int(round(lt['td_line'].eval()))
		on_target = (act == TARGET_ACT and line == TARGET_LINE)

	fade_dur = max(0.05, scriptOp.par.Focusfadeseconds.eval())
	target = 1.0 if on_target else 0.0
	step = dt / fade_dur
	if _state['focus'] < target:
		_state['focus'] = min(target, _state['focus'] + step)
	elif _state['focus'] > target:
		_state['focus'] = max(target, _state['focus'] - step)

	focus = _state['focus']

	period = max(0.05, scriptOp.par.Pulseperiod.eval())
	amount = scriptOp.par.Pulseamount.eval()
	glow_pulse = 1.0 + amount * focus * (0.5 + 0.5 * math.sin(2.0 * math.pi * now / period))

	vignette_alpha = focus * scriptOp.par.Vignettestrength.eval()

	for name, val in [
		('focus', focus),
		('glow_pulse', glow_pulse),
		('vignette_alpha', vignette_alpha),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
