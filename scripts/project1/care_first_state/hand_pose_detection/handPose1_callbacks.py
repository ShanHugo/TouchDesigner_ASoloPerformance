"""
Script CHOP Callbacks - hand_pose_detection/handPose1

Runs MediaPipe HandLandmarker (2 hands) on /project1/bodyGreenFX/cam1 and
detects a "hands pressed together" (prayer / joined-hands) pose, rather than
a single-hand pinch. Outputs:
  hands_present   - 1.0 when both hands are detected, else 0.0
  hands_joined    - 0..1 continuous score, how close/level the two palms are
  pose_x, pose_y  - average position of the two hands (mirrored/flip-corrected,
                    same convention as the old hand_x/hand_y: 1=top, mirrored x)

me - this DAT
scriptOp - the OP which is cooking
"""

from typing import Any
import sys
import numpy as np

_USER_SITE = r'C:\Users\Student\AppData\Roaming\Python\Python311\site-packages'
if _USER_SITE not in sys.path:
	sys.path.append(_USER_SITE)

import cv2
import mediapipe as mp
from mediapipe.tasks.python import vision as mp_vision
from mediapipe.tasks.python import BaseOptions

# shared GPU-downscaled camera: every detector used to pull the full 1280x720
# frame back from the GPU and resize it on the CPU - four times per frame
CAM_PATH = '/project1/care_first_state/camSmall1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (0, 1)  # Act 1 (hands-joined ritual) AND Act 2 (press_release's two-hand-down gesture)
MODEL_PATH = 'C:/Users/Student/Work/TD/models/hand_landmarker.task'
RESIZE_WIDTH = 480
INFERENCE_HZ = 12.0

_state = {
	'last_infer': -1e9,
	'last_out': None,
	'last_ts': 0,  # guards MediaPipe VIDEO mode's monotonic-timestamp requirement
	'landmarker': None,
	'last_x': 0.5,
	'last_y': 0.5,
}


def _get_landmarker():
	if _state['landmarker'] is None:
		options = mp_vision.HandLandmarkerOptions(
			base_options=BaseOptions(model_asset_path=MODEL_PATH),
			running_mode=mp_vision.RunningMode.VIDEO,
			num_hands=2,
			min_hand_detection_confidence=0.3,
			min_hand_presence_confidence=0.3,
			min_tracking_confidence=0.3,
		)
		_state['landmarker'] = mp_vision.HandLandmarker.create_from_options(options)
	return _state['landmarker']


def _palm_center(lm):
	return (
		(lm[0].x + lm[5].x + lm[9].x + lm[13].x + lm[17].x) / 5.0,
		(lm[0].y + lm[5].y + lm[9].y + lm[13].y + lm[17].y) / 5.0,
	)


def _hand_scale(lm):
	return ((lm[0].x - lm[9].x) ** 2 + (lm[0].y - lm[9].y) ** 2) ** 0.5


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('HandPose')
	p = page.appendFloat('Joinedmax', label='Joined Max Distance (scale-normalized)')
	p[0].default = 1.4
	p[0].val = 1.4
	p = page.appendFloat('Levelnesstolerance', label='Levelness Tolerance (y-diff, scale-normalized)')
	p[0].default = 1.2
	p[0].val = 1.2
	p = page.appendToggle('Mirrorx', label='Mirror X Output')
	p[0].default = True
	p[0].val = True
	p = page.appendFloat('Singlehandconfidence', label='Single-Hand Joined Confidence (occlusion fallback)')
	p[0].default = 0.75
	p[0].val = 0.75
	p[0].normMin = 0
	p[0].normMax = 1
	return


def onPulse(par: Any):
	return


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	# Rate-limit the MediaPipe inference: at full frame rate this model alone was
	# costing more than the entire frame budget. On skipped frames the previous
	# result is replayed so downstream values stay steady instead of flickering.
	_sw = op(SWITCH_PATH)
	_active = _sw is None or int(round(_sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	_now = absTime.seconds
	_due = (_now - _state['last_infer']) >= 1.0 / max(1.0, INFERENCE_HZ)
	if _active and not _due and _state.get('last_out'):
		for _nm, _v in _state['last_out']:
			_ch = scriptOp.appendChan(_nm)
			_ch[0] = _v
		return
	if _active:
		_state['last_infer'] = _now

	hands_present = 0.0
	hands_joined = 0.0
	hands_joined_strict = 0.0
	pose_x = _state['last_x']
	pose_y = _state['last_y']

	try:
		sw = op(SWITCH_PATH)
		# skip the expensive MediaPipe inference entirely while a different
		# scene is on screen - nothing reads this detector's output then, and
		# running it anyway just burns CPU every single frame for no reason
		is_active_scene = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
		cam = op(CAM_PATH) if is_active_scene else None
		if cam is not None:
			arr = cam.numpyArray(delayed=True)
			if arr is not None:
				h, w = arr.shape[0], arr.shape[1]
				rgb = (arr[:, :, :3] * 255.0).astype(np.uint8)
				if w > RESIZE_WIDTH:
					scale = RESIZE_WIDTH / float(w)
					rgb = cv2.resize(rgb, (RESIZE_WIDTH, int(h * scale)), interpolation=cv2.INTER_AREA)
				rgb = np.ascontiguousarray(rgb)

				mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
				landmarker = _get_landmarker()
				timestamp_ms = int(absTime.seconds * 1000)
				if timestamp_ms <= _state['last_ts']:
					# MediaPipe VIDEO mode requires strictly increasing timestamps;
					# int(ms) truncation can repeat the same value on back-to-back
					# cooks, which used to throw and silently blank the whole frame
					timestamp_ms = _state['last_ts'] + 1
				_state['last_ts'] = timestamp_ms
				result = landmarker.detect_for_video(mp_image, timestamp_ms)

				hands = result.hand_landmarks or []
				if len(hands) >= 2:
					cA = _palm_center(hands[0])
					cB = _palm_center(hands[1])
					scaleA = _hand_scale(hands[0])
					scaleB = _hand_scale(hands[1])
					avg_scale = max((scaleA + scaleB) / 2.0, 1e-4)

					raw_dist = ((cA[0] - cB[0]) ** 2 + (cA[1] - cB[1]) ** 2) ** 0.5
					joined_ratio = raw_dist / avg_scale

					y_diff = abs(cA[1] - cB[1]) / avg_scale

					joined_max = scriptOp.par.Joinedmax.eval()
					level_tol = scriptOp.par.Levelnesstolerance.eval()

					dist_score = max(0.0, min(1.0, 1.0 - joined_ratio / joined_max))
					level_score = max(0.0, min(1.0, 1.0 - y_diff / level_tol))

					hands_present = 1.0
					hands_joined = float(dist_score * level_score)
					hands_joined_strict = hands_joined

					mid_x = (cA[0] + cB[0]) / 2.0
					mid_y = (cA[1] + cB[1]) / 2.0
					if scriptOp.par.Mirrorx.eval():
						mid_x = 1.0 - mid_x

					pose_x = float(mid_x)
					pose_y = float(mid_y)  # raw mediapipe y: empirically 1=top, 0=bottom (see hand_pose_detection notes)

					_state['last_x'] = pose_x
					_state['last_y'] = pose_y
				elif len(hands) == 1:
					# Only one hand blob detected. This USED to also count as a
					# possible joined-hands pose (Singlehandconfidence fallback,
					# for the case where two clasped hands merge into one blob) -
					# but nothing here actually verified the two hands were really
					# together, so a single raised hand alone could false-trigger
					# the ritual. That occlusion case is now covered more reliably
					# by chest_alignment/poseTrack1's wrists_joined (full-body pose
					# tracking keeps estimating BOTH wrists even when HandLandmarker
					# only sees one blob, and it's gated on per-wrist detection
					# confidence) - so hands_joined stays 0 here; a lone hand no
					# longer contributes to the ritual on its own.
					hands_present = 1.0
					hands_joined = 0.0
					c = _palm_center(hands[0])
					mx = c[0]
					if scriptOp.par.Mirrorx.eval():
						mx = 1.0 - mx
					pose_x = float(mx)
					pose_y = float(c[1])
					_state['last_x'] = pose_x
					_state['last_y'] = pose_y
	except Exception as e:
		scriptOp.store('last_error', str(e))

	for name, val in [
		('hands_present', hands_present),
		('hands_joined', hands_joined),
		('hands_joined_strict', hands_joined_strict),
		('pose_x', pose_x),
		('pose_y', pose_y),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	_state['last_out'] = [(c.name, c[0]) for c in scriptOp.chans()]
	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
