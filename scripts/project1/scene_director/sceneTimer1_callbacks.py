"""
Script CHOP Callbacks - scene_director/sceneTimer1

Tracks elapsed time since this component first cooked (i.e. since the
project/experience started) and forces scene 1 -> scene 2 -> scene 3 in
sequence after fixed durations - a time-driven transition, not
gesture-driven, per the design rule that gestures only affect texture
within a scene and never decide scene changes.

Outputs:
  elapsed_seconds   - seconds since start
  time_remaining    - seconds left in the currently active scene
  scene1_active     - 1.0 while scene 1 should be showing
  scene2_active     - 1.0 while scene 2 should be showing
  scene3_active     - 1.0 while scene 3 should be showing
  active_scene_index - 0 / 1 / 2, which scene is currently active

me - this DAT
scriptOp - the OP which is cooking
"""

_state = {'start_time': None}


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('SceneTimer')
	p = page.appendFloat('Scene1duration', label='Scene 1 Duration (s)')
	p[0].default = 150.0
	p[0].val = 150.0
	p = page.appendFloat('Scene2duration', label='Scene 2 Duration (s)')
	p[0].default = 150.0
	p[0].val = 150.0
	p = page.appendFloat('Fadeduration', label='Crossfade Duration Before Scene Change (s)')
	p[0].default = 2.5
	p[0].val = 2.5
	p[0].normMin = 0.2
	p[0].normMax = 8.0
	p = page.appendPulse('Restarttimer', label='Restart Timer')
	return


def onPulse(par):
	if par.name == 'Restarttimer':
		_state['start_time'] = None
	return


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	if _state['start_time'] is None:
		_state['start_time'] = absTime.seconds

	d1 = max(scriptOp.par.Scene1duration.eval(), 0.1)
	d2 = max(scriptOp.par.Scene2duration.eval(), 0.1)
	elapsed = absTime.seconds - _state['start_time']

	if elapsed < d1:
		active_scene_index = 0
		remaining = d1 - elapsed
		scene_elapsed = elapsed
	elif elapsed < d1 + d2:
		active_scene_index = 1
		remaining = (d1 + d2) - elapsed
		scene_elapsed = elapsed - d1
	else:
		active_scene_index = 2
		remaining = None  # scene 3 is the ending - nothing to crossfade into
		scene_elapsed = elapsed - d1 - d2

	scene1_active = 1.0 if active_scene_index == 0 else 0.0
	scene2_active = 1.0 if active_scene_index == 1 else 0.0
	scene3_active = 1.0 if active_scene_index == 2 else 0.0

	# ramps 0->1 over the last Fadeduration seconds of the CURRENT scene,
	# then drops back to 0 the instant active_scene_index actually advances
	# (since remaining resets to a big number for the new scene) - drives a
	# crossTOP blending the current scene into the next one, instead of a
	# hard instant cut
	fade_dur = max(0.1, scriptOp.par.Fadeduration.eval())
	if remaining is not None and remaining <= fade_dur:
		transition_blend = 1.0 - max(0.0, remaining / fade_dur)
	else:
		transition_blend = 0.0
	next_scene_index = min(2, active_scene_index + 1)

	for name, val in [
		('elapsed_seconds', elapsed),
		('time_remaining', remaining if remaining is not None else 0.0),
		('scene1_active', scene1_active),
		('scene2_active', scene2_active),
		('scene3_active', scene3_active),
		('active_scene_index', float(active_scene_index)),
		('next_scene_index', float(next_scene_index)),
		('transition_blend', transition_blend),
		('scene_elapsed_seconds', scene_elapsed),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
