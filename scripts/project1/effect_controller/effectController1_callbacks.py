"""
Script CHOP Callbacks - effect_controller/effectController1

Step 0 of the teacher's visual plan (TD視覺風格設定.docx, section 5, "05 Effect
Controller"): the one place that turns the existing act state into the few named
0..1 parameters the new visual layers will read. Nothing reads these yet, so adding
this node changes no pixels.

  S1  sceneReveal, bloomStrength  - rise with Act 1's progress; hands joined at the
									chest (the vow) lifts bloom on top
  S2  sceneHeat, subjectHeat      - follow the feed count: cold -> +Heatperfeed per
									feed -> Heatburst once weary (3rd feed); pressing
									the clouds down cools it toward Presscooled. The
									subject runs Subjectlead above the room until the
									burst, then both overheat together
  S3  flameSize, flameGain,       - ember before the card lands, kindled when it lands,
	  flameStability                grows while the self-hug is held, full once the
									kintsugi gold has filled
  all textScale, textOffsetx/y    - plain values for the typography step

Parameters of an act that is not on screen rest at 0, so every visitor starts from
the dark / cold / ember state. Manual page: tick Manualparams to drive them by hand
(teacher's step B, "one parameter you can drag continuously").
"""

import math

SWITCH_PATH = '/project1/scene_director/switchScene1'
TIMER_PATH = '/project1/scene_director/sceneTimer1'
HAND_PATH = '/project1/care_first_state/hand_pose_detection/handPose1'
FEED_PATH = '/project1/care_second_state/feeding_state/feedingState1'
WEARY_PATH = '/project1/care_second_state/feeding_state/wearinessState1'
PHASE_PATH = '/project1/care_third_state/card_sense/act3PhaseState1'
EMBRACE_PATH = '/project1/care_third_state/embrace_sense/embraceState1'
KINTSUGI_PATH = '/project1/care_third_state/card_visual/kintsugiDraw1'

SMOOTHED = ('bloomStrength', 'sceneReveal', 'sceneHeat', 'subjectHeat',
			'flameSize', 'flameGain', 'flameStability')
MANUAL_PAR = {'bloomStrength': 'Bloomstrength', 'sceneReveal': 'Scenereveal',
			  'sceneHeat': 'Sceneheat', 'subjectHeat': 'Subjectheat',
			  'flameSize': 'Flamesize', 'flameGain': 'Flamegain',
			  'flameStability': 'Flamestability'}

_state = {'values': {n: 0.0 for n in SMOOTHED}, 'last_time': None, 'vow': 0.0, 'gold': 0.0}


def _clamp(v, lo=0.0, hi=1.0):
	return max(lo, min(hi, v))


def _read(path, name, default=0.0):
	# a Script CHOP that has not cooked yet this frame can hand back None
	try:
		o = op(path)
		c = o[name] if o is not None else None
		v = c.eval() if c is not None else None
		return default if v is None else float(v)
	except Exception:
		return default


def s1_targets(progress, vow, par):
	reveal = par['Revealstart'] + (1.0 - par['Revealstart']) * _clamp(progress)
	bloom = _clamp(0.1 + 0.6 * _clamp(progress) + par['Bloomvowboost'] * _clamp(vow))
	return {'sceneReveal': reveal, 'bloomStrength': bloom}


def s2_targets(feed_count, relief, par, line_burst=False, feed_may_burst=True):
	# line_burst: Act 2 reached 「我真的受不了了！」 - the red flood belongs to that
	# line, so it fires whether or not the feed count got there (feedingState1
	# publishes the flag as burst_pub)
	# feed_may_burst mirrors feedingState1's Burstmode. With that set to 'line'
	# the feed count must NOT detonate the act on its own: one extra feed flooded
	# the screen red during line 2, and relief had cleared it again before
	# 「我真的受不了了！」 arrived, so the line played on a calm picture.
	if (feed_may_burst and feed_count >= par['Feedstoburst']) or line_burst:
		heat = par['Heatburst'] + (par['Presscooled'] - par['Heatburst']) * _clamp(relief)
		subject = heat
	else:
		heat = par['Heatcold'] + par['Heatperfeed'] * max(0, feed_count)
		subject = heat + par['Subjectlead']
	return {'sceneHeat': _clamp(heat), 'subjectHeat': _clamp(subject)}


def s3_targets(landed, hold_frac, gold, par):
	if landed < 0.5:
		return {'flameSize': par['Flameember'], 'flameGain': par['Flameember'],
				'flameStability': 0.2}
	grow = max(0.35 * _clamp(hold_frac), _clamp(gold))
	p = par['Flamelanded'] + (1.0 - par['Flamelanded']) * grow
	return {'flameSize': p, 'flameGain': p, 'flameStability': 0.3 + 0.7 * _clamp(gold)}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Cues')
	for name, label, val in (
			('Smoothseconds', 'Smoothing Time (s)', 1.2),
			('Revealstart', 'S1 Reveal At Start', 0.15),
			('Bloomvowboost', 'S1 Bloom Boost While Vowing', 0.3),
			('Heatcold', 'S2 Heat Before Any Feed', 0.15),
			('Heatperfeed', 'S2 Heat Added Per Feed', 0.15),
			('Heatburst', 'S2 Heat At The Burst', 0.9),
			('Presscooled', 'S2 Heat Once Fully Pressed Down', 0.35),
			('Subjectlead', 'S2 Subject Warmer Than Room By', 0.15),
			('Flameember', 'S3 Flame Before Card Lands', 0.1),
			('Flamelanded', 'S3 Flame When Card Lands', 0.3)):
		p = page.appendFloat(name, label=label)
		p[0].default = val
		p[0].val = val
	p = page.appendFloat('Goldfillseconds', label='S3 Seconds From Embrace To Full Flame')
	p[0].default = 5.0
	p[0].val = 5.0
	p = page.appendInt('Feedstoburst', label='S2 Feeds To Burst')
	p[0].default = 3
	p[0].val = 3
	page = scriptOp.appendCustomPage('Manual')
	p = page.appendToggle('Manualparams', label='Drive Parameters By Hand')
	p[0].default = False
	p[0].val = False
	for name in ('Bloomstrength', 'Scenereveal', 'Sceneheat', 'Subjectheat',
				 'Flamesize', 'Flamegain', 'Flamestability'):
		p = page.appendFloat(name)
		p[0].default = 0.0
		p[0].val = 0.0
	for name, val in (('Textscale', 1.0), ('Textoffsetx', 0.0), ('Textoffsety', 0.0)):
		p = page.appendFloat(name)
		p[0].default = val
		p[0].val = val
	return


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	now = absTime.seconds
	dt = 0.0 if _state['last_time'] is None else max(0.0, now - _state['last_time'])
	_state['last_time'] = now

	par = {p.name: p.eval() for p in scriptOp.customPars}
	targets = {n: 0.0 for n in SMOOTHED}
	vow_target = 0.0
	ignite = 0.0
	try:
		sw = op(SWITCH_PATH)
		act = int(round(sw.par.index.eval())) if sw is not None else 0
		if act == 0:
			vow_target = _clamp(_read(HAND_PATH, 'hands_joined_strict'))
			dur = op(TIMER_PATH).par.Scene1duration.eval() if op(TIMER_PATH) is not None else 150.0
			progress = _read(TIMER_PATH, 'scene_elapsed_seconds') / max(1.0, dur)
			targets.update(s1_targets(progress, _read(HAND_PATH, 'hands_joined_strict'), par))
		elif act == 1:
			fs = op(FEED_PATH)
			count = int(round(fs.fetch('feed_count_pub', 0.0))) if fs is not None else 0
			burst_line = (fs.fetch('burst_pub', 0.0) > 0.5) if fs is not None else False
			feed_may_burst = True
			if fs is not None and hasattr(fs.par, 'Burstmode'):
				feed_may_burst = str(fs.par.Burstmode.eval()) in ('feed', 'both')
			targets.update(s2_targets(count, _read(WEARY_PATH, 'relief'), par, burst_line, feed_may_burst))
		elif act == 2:
			es = op(EMBRACE_PATH)
			hp = getattr(es.par, 'Holdseconds', None) if es is not None else None
			hold = hp.eval() if hp is not None else 2.0
			# 'the embrace has filled' is timed here, not read from kintsugiDraw1: step 4
			# (candle) takes the kintsugi picture off screen, and an unviewed TOP may stop
			# cooking - the flame would then never reach full. Same timing as the kintsugi
			# gold: starts when the embrace latches, clears when embraceState1 auto-resets.
			if _read(EMBRACE_PATH, 'embraced') > 0.5:
				_state['gold'] = min(1.0, _state['gold'] + dt / max(0.1, par['Goldfillseconds']))
			else:
				_state['gold'] = 0.0
			gold = _state['gold']
			landed_s = _read(PHASE_PATH, 'landed_seconds')
			if _read(PHASE_PATH, 'landed') > 0.5:
				ignite = math.exp(-2.5 * max(0.0, landed_s))   # the card lighting the flame
			targets.update(s3_targets(_read(PHASE_PATH, 'landed'),
									  _read(EMBRACE_PATH, 'held_seconds') / max(0.1, hold), gold, par))
	except Exception as e:
		scriptOp.store('last_error', str(e))

	tau = max(0.01, par['Smoothseconds'])
	k = 1.0 - math.exp(-dt / tau)
	manual = par['Manualparams']
	for n in SMOOTHED:
		_state['values'][n] += (targets[n] - _state['values'][n]) * k
		val = par[MANUAL_PAR[n]] if manual else _state['values'][n]
		scriptOp.appendChan(n)[0] = val
	tau_vow = 0.25 if vow_target > _state['vow'] else 1.0
	_state['vow'] += (vow_target - _state['vow']) * (1.0 - math.exp(-dt / tau_vow))
	scriptOp.appendChan('vowBoost')[0] = _state['vow']
	scriptOp.appendChan('flameIgnite')[0] = ignite
	for n, pn in (('textScale', 'Textscale'), ('textOffsetx', 'Textoffsetx'), ('textOffsety', 'Textoffsety')):
		scriptOp.appendChan(n)[0] = par[pn]
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
