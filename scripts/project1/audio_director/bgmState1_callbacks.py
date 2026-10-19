"""
Script CHOP Callbacks - audio_director/bgmState1

One BGM per act, equal-power crossfaded on the act change. Follows
lineTrack1's td_act, so it tracks the rehearsal panel's Manualoverride /
Manualscene exactly like the visuals do - jumping to Act 3 by hand brings
Act 3's music with it.

Bgmmaster and Bgmmute both live on scene_director's ManualControl page, with
the rest of the rehearsal controls; this node keeps no second copy of either.

The three tracks are NOT level-matched as supplied (mean volume: scene 1
-22.0 dB, scene 2 -13.0 dB, scene 3 -17.1 dB), so each has a trim that
brings it down to the quietest of the three. Set the overall level with
Bgmmaster; the trims only keep the three relative to each other.

All three files are shorter than their acts (138 / 126 / 102 s against
150 / 150 / open-ended), so every Audio File In repeats. Each track is also
re-cued to its start when its act begins, so every visitor hears the piece
from the top rather than wherever the previous one left it.

Outputs:
  gain1/2/3   final volume for each Audio File In (trim * crossfade * master)
  act         the act currently driving the music
  fade        0..1 progress of the running crossfade (1 = settled)

me - this DAT
scriptOp - the OP which is cooking
"""

import math

LINETRACK_PATH = '/project1/scene_director/lineTrack1'
SD_PATH = '/project1/scene_director'
PLAYERS = ('/project1/audio_director/bgmScene1',
           '/project1/audio_director/bgmScene2',
           '/project1/audio_director/bgmScene3')

_state = {
	'act': 0,
	'prev_act': 0,
	'change_at': None,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Bgm')
	p = page.appendFloat('Fadeseconds', label='Crossfade Between Acts (s)')
	p[0].default = 2.5          # same as sceneTimer1's visual Fadeduration
	p[0].val = 2.5
	p[0].normMin = 0.0
	p[0].normMax = 15.0
	# trims measured with ffmpeg volumedetect, matched to the quietest track
	for name, label, default in (('Scene1trim', 'Act 1 Trim  (-22.0 dB source)', 1.0),
	                             ('Scene2trim', 'Act 2 Trim  (-13.0 dB source)', 0.355),
	                             ('Scene3trim', 'Act 3 Trim  (-17.1 dB source)', 0.569)):
		p = page.appendFloat(name, label=label)
		p[0].default = default
		p[0].val = default
		p[0].normMin = 0.0
		p[0].normMax = 2.0
	p = page.appendToggle('Recueonact', label='Restart The Track When Its Act Begins')
	p[0].default = True
	p[0].val = True
	return


def _cue(index):
	"""Send one track back to its start (index is 0-based)."""
	pl = op(PLAYERS[index])
	if pl is None:
		return
	try:
		pl.par.cuepulse.pulse()
	except Exception:
		pass


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60
	now = absTime.seconds

	lt = op(LINETRACK_PATH)
	act = 0
	if lt is not None and lt['td_act'] is not None:
		act = int(round(lt['td_act'].eval()))
	if act < 1 or act > 3:
		act = 0

	if act != _state['act']:
		_state['prev_act'] = _state['act']
		_state['act'] = act
		_state['change_at'] = now
		if act >= 1 and scriptOp.par.Recueonact.eval():
			_cue(act - 1)

	fade = max(0.0, scriptOp.par.Fadeseconds.eval())
	t = 1.0
	if _state['change_at'] is not None and fade > 0.0:
		t = max(0.0, min(1.0, (now - _state['change_at']) / fade))

	# equal power, so the pair does not dip in the middle of the crossfade
	g_in = math.sin(t * math.pi * 0.5)
	g_out = math.cos(t * math.pi * 0.5)

	gains = [0.0, 0.0, 0.0]
	if 1 <= _state['act'] <= 3:
		gains[_state['act'] - 1] += g_in
	if 1 <= _state['prev_act'] <= 3 and t < 1.0:
		gains[_state['prev_act'] - 1] += g_out

	# the mute lives on scene_director's ManualControl page so it sits with the
	# rest of the rehearsal controls; this node holds no second copy of it
	sd = op(SD_PATH)
	muted = bool(sd.par.Bgmmute.eval()) if (sd is not None and hasattr(sd.par, 'Bgmmute')) else False
	level = sd.par.Bgmmaster.eval() if (sd is not None and hasattr(sd.par, 'Bgmmaster')) else 0.5
	# standby: Unity is on its own start screen, so the music drops to a bed
	# rather than stopping - a silent room reads as "broken", not as "waiting"
	sb = op('/project1/scene_director/standbyState1')
	if sb is not None and sb['fade'] is not None:
		f = max(0.0, min(1.0, sb['fade'].eval()))
		duck = sb.par.Bgmlevel.eval() if hasattr(sb.par, 'Bgmlevel') else 0.35
		level = level * (1.0 + (duck - 1.0) * f)
	master = 0.0 if muted else level
	trims = [scriptOp.par.Scene1trim.eval(),
	         scriptOp.par.Scene2trim.eval(),
	         scriptOp.par.Scene3trim.eval()]

	for i in range(3):
		chan = scriptOp.appendChan('gain%d' % (i + 1))
		chan[0] = max(0.0, gains[i] * trims[i] * master)
	chan = scriptOp.appendChan('act')
	chan[0] = float(_state['act'])
	chan = scriptOp.appendChan('fade')
	chan[0] = t
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
