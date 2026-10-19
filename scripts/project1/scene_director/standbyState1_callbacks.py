"""
Script CHOP Callbacks - scene_director/standbyState1

Unity shows its own "開始體驗" screen before a visitor starts, and sends 000
(act 0) while it is up. TD has nothing to show during that, so it holds a
standby frame instead of leaving the last visitor's ending on screen.

Standby is entered ONLY when Unity is CONNECTED and LIVE and reporting act 0.
Both tests are needed: unity_live falls back to a cook-based guess when Unity
sends no /Alive heartbeat, and that guess fires on any cook at all, so on its
own it put TD into standby with Unity shut down. With no Unity on the line TD
keeps running its own timeline exactly as before - a missing Unity must not
blank the screen.

Manualstandby on scene_director's ManualControl page forces it either way for
rehearsal.

Leaving standby is what restarts the piece: Unity goes 000 -> 111, which is the
edge lineTrack1's Restartonunityfirstline already watches, so the timeline
rewinds to the top for the new visitor without anything extra here.

Outputs:
  standby    0/1 target state
  fade       0..1 eased, drives the cross-fade to the standby frame and the
             BGM duck
  unity_act  what Unity is reporting, for the debug panel

me - this DAT
scriptOp - the OP which is cooking
"""

OSCSYNC_PATH = '/project1/scene_director/oscSync1'
SD_PATH = '/project1/scene_director'

_state = {'fade': 0.0, 'last_time': None}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Standby')
	p = page.appendFloat('Fadeseconds', label='Fade To / From Standby (s)')
	p[0].default = 1.5
	p[0].val = 1.5
	p[0].normMin = 0.0
	p[0].normMax = 10.0
	p = page.appendFloat('Brightness', label='Standby Brightness')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	p = page.appendFloat('Breathedepth', label='Breathe Depth')
	p[0].default = 0.45
	p[0].val = 0.45
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	p = page.appendFloat('Breatheseconds', label='Breathe Period (s)')
	p[0].default = 7.0
	p[0].val = 7.0
	p[0].normMin = 1.0
	p[0].normMax = 20.0
	p = page.appendFloat('Bgmlevel', label='BGM Level While Standing By')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0.0
	p[0].normMax = 1.0
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	now = absTime.seconds
	dt = 0.0 if _state['last_time'] is None else max(0.0, now - _state['last_time'])
	_state['last_time'] = now

	sy = op(OSCSYNC_PATH)
	# unity_live alone is NOT enough: with no /Alive channel it falls back to
	# "did the OSC In CHOP cook", which anything can trigger - clearing the
	# channels was enough to report live with Unity shut down, and TD then sat
	# in standby forever. unity_connected only goes true once real act/line/bg
	# packets have actually arrived, so require both.
	live = sy['unity_live'].eval() > 0.5 if sy is not None else False
	connected = sy['unity_connected'].eval() > 0.5 if sy is not None else False
	u_act = int(round(sy['unity_act'].eval())) if sy is not None else 0

	sd = op(SD_PATH)
	mode = str(sd.par.Manualstandby.eval()) if (sd is not None and hasattr(sd.par, 'Manualstandby')) else 'auto'
	if mode == 'on':
		target = 1.0
	elif mode == 'off':
		target = 0.0
	else:
		# auto: only a CONNECTED and LIVE Unity sitting on act 0 puts TD into standby
		target = 1.0 if (connected and live and u_act == 0) else 0.0

	dur = max(0.0, scriptOp.par.Fadeseconds.eval())
	if dur <= 0.0 or dt <= 0.0:
		_state['fade'] = target
	else:
		step = dt / dur
		if target > _state['fade']:
			_state['fade'] = min(target, _state['fade'] + step)
		else:
			_state['fade'] = max(target, _state['fade'] - step)

	for name, val in [
		('standby', target),
		('fade', _state['fade']),
		('unity_act', float(u_act)),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
