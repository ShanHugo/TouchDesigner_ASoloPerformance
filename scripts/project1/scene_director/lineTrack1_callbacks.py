"""
Script CHOP Callbacks - scene_director/lineTrack1

Subdivides each act's own duration (from sceneTimer1's scene_elapsed_seconds)
into the individual scripted dialogue lines for that act, so TD always knows
"which line should be showing right now" purely from its own internal
timeline.

Line-start times (seconds since the CURRENT act began) are exposed as
custom pars so timing can be retuned without touching code. Line 1 of every
act always starts at scene_elapsed_seconds == 0, so it needs no par.

Encoding matches Unity's OSC convention exactly:
  code = act*100 + line*10 + background   (act/line/background are each 1-9)
  e.g. "111" = Act 1, Line 1, Background 1

FOLLOW-UNITY MODE (Followunity toggle, default OFF):
  When OFF - TD runs its own timeline, oscSync1 only reports agreement.
  When ON  - if Unity's reported (act,line) disagrees with TD's for longer
             than Resyncafterseconds AND Unity is live (oscSync1.unity_live),
             TD seeks its own timeline (sceneTimer1's start_time) to the
             start of the line Unity reports, plus Resyncnudgeseconds so it
             lands firmly inside that line. A Resynccooldownseconds gate
             stops it from re-seeking every frame. Requires scene_director
             Manualoverride to be OFF (otherwise switchScene1 ignores the
             timeline). This is a hard snap, not a crossfade - a drift
             correction is meant to be immediate.

td_code / td_act / td_line are also written to scene_director storage each
cook so oscSync1 can read them without creating a cook loop (lineTrack1
reads oscSync1's outputs in follow mode).

Outputs:
  td_act        - 1/2/3, current act
  td_line       - 1-based line index within the current act
  td_bg         - current background code (Backgroundcode par)
  td_code       - the full 3-digit comparison code, act*100+line*10+bg

me - this OP
scriptOp - the OP which is cooking
"""

SCENETIMER_PATH = '/project1/scene_director/sceneTimer1'
SCENETIMER_CB_PATH = '/project1/scene_director/sceneTimer1_callbacks'
OSCSYNC_PATH = '/project1/scene_director/oscSync1'
TEXT_DAT_PATH = '/project1/scene_director/currentLineText1'
SD_PATH = '/project1/scene_director'

LINES_PER_ACT = {1: 3, 2: 4, 3: 3}

LINES = {
	1: {
		1: "你是否願意與眼前這個人結為伴侶......不論對方生病或是健康、富有或貧窮，始終忠於對方，直到離開世界？",
		2: "我願意......",
		3: "牽我的手，走我們的路，牽你的手，不怕艱苦。",
	},
	2: {
		1: "他們看著我帶另一半來，都不知道該說些什麼。看我餵對方吃飯，他們也覺得尷尬。",
		2: "我好累！我擔心的是自己想不開，我都覺得自己快要憂鬱症了！",
		3: "我真的受不了了！",
		4: "大姊，我懂......我想跟大姊說，其實你並不孤單。",
	},
	3: {
		1: "請跟著直覺抽一張牌。先不要看文字，只看圖像。",
		2: "照顧者常常給出太多，今天，讓我們回到「你自己」的身上。",
		3: "當你付出愛，也要讓愛回到自己身上。",
	},
}

_state = {
	'prev_unity_line': None,
	'unity_first_line_since': None,
	'restart_fired': False,
	'follow_mismatch_since': None,
	'last_seek_time': -1e9,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('LineSchedule')

	def add(name, label, default):
		p = page.appendFloat(name, label=label)
		p[0].default = default
		p[0].val = default
		p[0].normMin = 0.0
		p[0].normMax = 150.0

	add('Act1line2start', 'Act 1 Line 2 Start (s into act)', 50.0)
	add('Act1line3start', 'Act 1 Line 3 Start (s into act)', 100.0)
	add('Act2line2start', 'Act 2 Line 2 Start (s into act)', 37.5)
	add('Act2line3start', 'Act 2 Line 3 Start (s into act)', 75.0)
	add('Act2line4start', 'Act 2 Line 4 Start (s into act)', 112.5)
	add('Act3line2start', 'Act 3 Line 2 Start (s into act)', 10.0)
	add('Act3line3start', 'Act 3 Line 3 Start (s into act)', 20.0)

	p = page.appendInt('Backgroundcode', label='Background Code (all lines)')
	p[0].default = 1
	p[0].val = 1
	p[0].normMin = 1
	p[0].normMax = 9

	page2 = scriptOp.appendCustomPage('FollowUnity')
	p = page2.appendToggle('Followunity', label='Follow Unity (seek TD to match)')
	p[0].default = False
	p[0].val = False
	p = page2.appendFloat('Resyncafterseconds', label='Resync After Mismatch (s)')
	p[0].default = 3.0
	p[0].val = 3.0
	p[0].normMin = 0.5
	p[0].normMax = 15.0
	p = page2.appendFloat('Resyncnudgeseconds', label='Resync Land Past Line Start (s)')
	p[0].default = 0.5
	p[0].val = 0.5
	p[0].normMin = 0.0
	p[0].normMax = 5.0
	p = page2.appendFloat('Resynccooldownseconds', label='Min Seconds Between Seeks')
	p[0].default = 2.5
	p[0].val = 2.5
	p[0].normMin = 0.5
	p[0].normMax = 15.0
	p = page2.appendToggle('Restartonunityfirstline', label='Restart When Unity Switches To Act 1 Line 1 (next visitor)')
	p[0].default = True
	p[0].val = True
	p = page2.appendFloat('Restartholdseconds', label='Unity Must Hold Act 1 Line 1 This Long (s)')
	p[0].default = 1.5
	p[0].val = 1.5
	p[0].normMin = 0.0
	p[0].normMax = 10.0
	return


def _line_thresholds(act, scriptOp):
	p = scriptOp.par
	if act == 1:
		return [p.Act1line2start.eval(), p.Act1line3start.eval()]
	if act == 2:
		return [p.Act2line2start.eval(), p.Act2line3start.eval(), p.Act2line4start.eval()]
	return [p.Act3line2start.eval(), p.Act3line3start.eval()]


def _current_line(act, scene_elapsed, scriptOp):
	line = 1
	for i, t in enumerate(_line_thresholds(act, scriptOp)):
		if scene_elapsed >= t:
			line = i + 2
	return line


def _seek_timeline_to(act, line, scriptOp, nudge=True):
	"""Move sceneTimer1's start_time so its elapsed lands at the start of
	(act, line). act is 1/2/3, line is 1-based. The Resyncnudgeseconds lead
	exists for Unity resyncs only - a manual scene pick passes nudge=False so
	the act starts at exactly 0."""
	st = op(SCENETIMER_PATH)
	stmod = op(SCENETIMER_CB_PATH).module
	if st is None or stmod is None:
		return False
	d1 = max(0.1, st.par.Scene1duration.eval())
	d2 = max(0.1, st.par.Scene2duration.eval())
	base = (0.0, 0.0, d1, d1 + d2)[act]
	if line <= 1:
		line_start = 0.0
	else:
		line_start = getattr(scriptOp.par, 'Act%dline%dstart' % (act, line)).eval()
	target_elapsed = base + line_start + (scriptOp.par.Resyncnudgeseconds.eval() if nudge else 0.0)
	stmod._state['start_time'] = absTime.seconds - target_elapsed
	return True


def _restart_on_new_visitor(td_act, td_line, scriptOp, st):
	"""Next visitor: when Unity switches INTO Act 1 / Line 1 from any other
	line, restart TD's timeline from the top. Every act resets its own state on
	entry, so walking the timeline again from Act 1 gives the new visitor a
	clean run. Edge-triggered (Unity holding 111 does not keep restarting) and
	skipped when TD is already in Act 1 / Line 1 (nothing to restart)."""
	sy = op(OSCSYNC_PATH)
	if sy is None:
		return
	live = sy['unity_live'].eval() > 0.5
	cur = (int(round(sy['unity_act'].eval())), int(round(sy['unity_line'].eval()))) if live else None
	prev = _state['prev_unity_line']
	_state['prev_unity_line'] = cur
	now = absTime.seconds
	if cur != (1, 1):
		# away from the first line - re-arm for the next visitor
		_state['unity_first_line_since'] = None
		_state['restart_fired'] = False
		return

	if prev != (1, 1):
		_state['unity_first_line_since'] = now

	if not scriptOp.par.Restartonunityfirstline.eval() or _state['restart_fired']:
		return

	# Unity must SETTLE on Act 1 / Line 1. Without this, a value that merely sweeps
	# through 1/1 while someone edits the Unity fields restarts the whole piece -
	# which is exactly what happened during the first two-machine test.
	held = now - (_state['unity_first_line_since'] or now)
	if held < scriptOp.par.Restartholdseconds.eval():
		return

	_state['restart_fired'] = True  # one restart per arrival, no repeats while Unity idles here
	if (td_act, td_line) != (1, 1):
		st.par.Restarttimer.pulse()
		_state['follow_mismatch_since'] = None
		_state['last_seek_time'] = now


def _follow_unity(td_act, td_line, scriptOp):
	now = absTime.seconds
	sy = op(OSCSYNC_PATH)
	if sy is None:
		_state['follow_mismatch_since'] = None
		return
	live = sy['unity_live'].eval() > 0.5
	u_act = int(round(sy['unity_act'].eval()))
	u_line = int(round(sy['unity_line'].eval()))

	valid = live and (1 <= u_act <= 3) and (1 <= u_line <= LINES_PER_ACT[u_act])
	if not valid or (u_act, u_line) == (td_act, td_line):
		_state['follow_mismatch_since'] = None
		return

	if _state['follow_mismatch_since'] is None:
		_state['follow_mismatch_since'] = now
		return

	held = now - _state['follow_mismatch_since']
	cooled = now - _state['last_seek_time']
	if held >= scriptOp.par.Resyncafterseconds.eval() and cooled >= scriptOp.par.Resynccooldownseconds.eval():
		if _seek_timeline_to(u_act, u_line, scriptOp):
			_state['last_seek_time'] = now
			_state['follow_mismatch_since'] = None


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	st = op(SCENETIMER_PATH)
	if st is None:
		return

	active_scene_index = int(round(st['active_scene_index'].eval()))
	scene_elapsed = st['scene_elapsed_seconds'].eval()
	act = active_scene_index + 1  # 0/1/2 -> 1/2/3

	# --- rehearsal overrides (scene_director): Manualoverride already pins which
	# act is SHOWN, so the subtitle has to follow it or the two disagree - which is
	# exactly what happened when a manual "Act 1" test ran with td_act still 2.
	# Manuallines additionally pins the line, for stepping through the script.
	sd_comp = op(SD_PATH)
	manual_act = False
	try:
		if getattr(sd_comp.par, 'Manualoverride', None) is not None and sd_comp.par.Manualoverride.eval():
			act = {'scene1': 1, 'scene2': 2, 'scene3': 3}.get(str(sd_comp.par.Manualscene.eval()), act)
			manual_act = True
	except Exception:
		pass

	line = _current_line(act, scene_elapsed, scriptOp)
	manual_line = False
	try:
		if getattr(sd_comp.par, 'Manuallines', None) is not None and sd_comp.par.Manuallines.eval():
			line = max(1, min(LINES_PER_ACT.get(act, 1), int(sd_comp.par.Manualline.eval())))
			manual_line = True
	except Exception:
		pass
	bg = int(scriptOp.par.Backgroundcode.eval())
	code = act * 100 + line * 10 + bg

	sd = op(SD_PATH)
	sd.store('td_code', code)
	sd.store('td_act', act)
	sd.store('td_line', line)

	_restart_on_new_visitor(act, line, scriptOp, st)

	if scriptOp.par.Followunity.eval():
		_follow_unity(act, line, scriptOp)
	else:
		_state['follow_mismatch_since'] = None

	for name, val in [
		('td_act', float(act)),
		('td_line', float(line)),
		('td_bg', float(bg)),
		('td_code', float(code)),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	text_dat = op(TEXT_DAT_PATH)
	if text_dat is not None:
		txt = LINES.get(act, {}).get(line, '')
		if text_dat.text != txt:
			text_dat.text = txt

	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
