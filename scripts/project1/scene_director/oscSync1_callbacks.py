"""
Script CHOP Callbacks - scene_director/oscSync1

Decodes Unity's OSC sync messages and compares them against TD's own
time-driven act/line/background state (lineTrack1).

Unity (OSCConnect/Assets/Scripts/OSCTest.cs) sends THREE separate int OSC
messages every frame, all 1-based.

  !! The two address labels are SWAPPED on the Unity side !!
  OSCTest.Update() sends the value of its `scriptLine` field under the
  address /SceneID, and the value of its `sceneID` field under /ScriptLine.
  That is her code and her wire format, so TD follows it rather than asking
  for a fix: the ACT arrives on the channel named ScriptLine and the LINE on
  the channel named SceneID. That is why the Actchannel / Linechannel
  defaults below look back to front - they are correct, do not "fix" them.

  channel ScriptLine  carries Unity's sceneID     -> act         (1-3)
  channel SceneID     carries Unity's scriptLine  -> line        (1-based in the act)
  channel SceneBK     carries Unity's sceneBK     -> background  (1-9)

If the mapping is ever corrected on the Unity side, swap the two
Actchannel / Linechannel par VALUES back - no code change is needed.
The OSC In CHOP strips the leading slash, so they arrive as channels named
by the Actchannel / Linechannel / Bgchannel pars. They are combined into the
same comparison code lineTrack1 uses: act*100 + line*10 + bg (111 = Act 1,
Line 1, Background 1).

Liveness: Unity sends /Alive, an int that increments every one of its frames
(Alivechannel). While that number keeps CHANGING, Unity is running; when it
freezes, Unity has hung or quit even though its last values are still sitting
in the OSC In CHOP. unity_live holds for Livetimeoutseconds after the last
change.

The old test - "did the OSC In CHOP cook by itself" - is kept as a fallback
for when the heartbeat channel is absent, but it is a FALSE POSITIVE detector:
anything that makes that CHOP cook reads as Unity being alive, so with Unity
shut down entirely it still reported live. Only the counter can tell a crash
from a quiet moment.

td_code comes from scene_director storage (written by lineTrack1) so
lineTrack1 can read this node's outputs without a cook loop.

Outputs:
  unity_code        act*100+line*10+bg (0 if any of the 3 channels is missing)
  unity_act/line/bg decoded components
  td_code           TD's own current code
  synced            1.0 only if unity_live AND unity_code == td_code
  mismatch_seconds  how long not-synced has been continuous
  unity_connected   1.0 once all three channels have been received
  unity_live        1.0 while Unity is actively sending packets
"""

OSC_PATH = '/project1/scene_director/oscInFromUnity1'
SD_PATH = '/project1/scene_director'

_state = {
	'mismatch_since': None,
	'prev_cook_frame': None,
	'last_live_time': None,
	'prev_beat': None,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('OscSync')
	for name, label, default in [
		('Actchannel', 'Act Channel Name', 'ScriptLine'),      # yes, ScriptLine - see the swap note above
		('Linechannel', 'Line Channel Name', 'SceneID'),       # yes, SceneID - see the swap note above
		('Bgchannel', 'Background Channel Name', 'SceneBK'),
	]:
		p = page.appendStr(name, label=label)
		p[0].default = default
		p[0].val = default
	p = page.appendStr('Alivechannel', label='Heartbeat Channel Name')
	p[0].default = 'Alive'
	p[0].val = 'Alive'
	p = page.appendFloat('Livetimeoutseconds', label='Unity Live Timeout (s)')
	p[0].default = 1.5
	p[0].val = 1.5
	p[0].normMin = 0.3
	p[0].normMax = 10.0
	return


def _read_unity_values(scriptOp):
	osc = op(OSC_PATH)
	if osc is None:
		return None
	chans = {c.name: c for c in osc.chans()}
	names = [scriptOp.par.Actchannel.eval().strip(),
	         scriptOp.par.Linechannel.eval().strip(),
	         scriptOp.par.Bgchannel.eval().strip()]
	if not all(n in chans for n in names):
		return None
	return tuple(int(round(chans[n].eval())) for n in names)


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60
	now = absTime.seconds

	osc = op(OSC_PATH)
	osc_cook_frame = osc.cookAbsFrame if osc is not None else 0

	# preferred: Unity's /Alive counter actually moving
	beat = None
	if osc is not None and hasattr(scriptOp.par, 'Alivechannel'):
		nm = scriptOp.par.Alivechannel.eval().strip()
		if nm:
			for c in osc.chans():
				if c.name == nm:
					beat = int(round(c.eval()))
					break
	if beat is not None:
		if _state['prev_beat'] is None or beat != _state['prev_beat']:
			_state['last_live_time'] = now
		_state['prev_beat'] = beat
	elif _state['prev_cook_frame'] is not None and osc_cook_frame > _state['prev_cook_frame']:
		# fallback only while no heartbeat channel exists - see the note above
		_state['last_live_time'] = now
	_state['prev_cook_frame'] = absTime.frame

	unity_live = (_state['last_live_time'] is not None
	              and (now - _state['last_live_time']) < scriptOp.par.Livetimeoutseconds.eval())

	td_code = int(round(op(SD_PATH).fetch('td_code', 0)))

	vals = _read_unity_values(scriptOp)
	unity_connected = vals is not None
	unity_act, unity_line, unity_bg = vals if vals is not None else (0, 0, 0)
	unity_code = unity_act * 100 + unity_line * 10 + unity_bg if unity_connected else 0

	synced = 1.0 if (unity_live and unity_code == td_code) else 0.0
	if synced > 0.5:
		_state['mismatch_since'] = None
		mismatch_seconds = 0.0
	else:
		if _state['mismatch_since'] is None:
			_state['mismatch_since'] = now
		mismatch_seconds = now - _state['mismatch_since']

	debug_dat = op('/project1/scene_director/oscSyncDebug1')
	if debug_dat is not None:
		if not unity_connected:
			status = 'NO OSC DATA'
		elif not unity_live:
			status = 'UNITY OFFLINE (stale value)'
		elif synced > 0.5:
			status = 'IN SYNC'
		else:
			status = 'MISMATCH'
		lines = [
			'OSC SYNC CHECK  -  ' + status,
			'TD    act/line/bg = %d / %d / %d   (code %03d)' % (td_code // 100, (td_code // 10) % 10, td_code % 10, td_code),
			'Unity act/line/bg = %d / %d / %d   (code %03d)' % (unity_act, unity_line, unity_bg, unity_code),
			'mismatch for %.1fs' % mismatch_seconds if synced < 0.5 else '',
		]
		txt = chr(10).join(l for l in lines if l)
		if debug_dat.text != txt:
			debug_dat.text = txt

	for name, val in [
		('unity_code', float(unity_code)),
		('unity_act', float(unity_act)),
		('unity_line', float(unity_line)),
		('unity_bg', float(unity_bg)),
		('td_code', float(td_code)),
		('synced', synced),
		('mismatch_seconds', mismatch_seconds),
		('unity_connected', 1.0 if unity_connected else 0.0),
		('unity_live', 1.0 if unity_live else 0.0),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
