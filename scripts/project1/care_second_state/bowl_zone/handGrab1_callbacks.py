"""
Script CHOP Callbacks - bowl_zone/handGrab1

Scene-2-specific single-hand pinch/grab detector, independent of Act 1's
two-hand "joined" detection (hand_pose_detection/handPose1). Runs its own
MediaPipe HandLandmarker instance on the shared camera feed.

pinch_distance is normalized by hand scale (wrist -> middle-finger MCP) so
it doesn't depend on how far the hand is from the camera.

Outputs:
  hand_active     - 1.0 if a hand is detected
  hand_x, hand_y  - hand position (mirrored, 1=top convention, matches
                    the rest of the project)
  pinch_distance  - scale-normalized thumb-index distance
  grab_value      - 0..1, how "closed" the pinch is
  grab_active     - 1.0 while grab_value is above the threshold

me - this DAT
scriptOp - the OP which is cooking
"""

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
ACTIVE_SCENE_INDICES = (1, 2)  # needed by Act 2 (bowl grab) and Act 3 (card draw, reused)
MODEL_PATH = 'C:/Users/Student/Work/TD/models/hand_landmarker.task'
RESIZE_WIDTH = 480
# Hand tracking does not need a fresh inference every frame - this was ~34ms of CPU
# per frame on its own. Between inferences the last detection is held, so the
# outputs stay steady instead of flickering on the skipped frames.
INFERENCE_HZ = 12.0

_state = {
	'last_infer': -1e9,
	'last_active': 0.0,
	'last_ts': 0,  # guards MediaPipe VIDEO mode's monotonic-timestamp requirement
	'landmarker': None,
	'last_x': 0.5,
	'last_y': 0.5,
	'last_pinch': 1.0,
}


def _get_landmarker():
	if _state['landmarker'] is None:
		options = mp_vision.HandLandmarkerOptions(
			base_options=BaseOptions(model_asset_path=MODEL_PATH),
			running_mode=mp_vision.RunningMode.VIDEO,
			num_hands=1,
			min_hand_detection_confidence=0.3,
			min_hand_presence_confidence=0.3,
			min_tracking_confidence=0.3,
		)
		_state['landmarker'] = mp_vision.HandLandmarker.create_from_options(options)
	return _state['landmarker']


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('HandGrab')
	p = page.appendFloat('Pinchmax', label='Pinch Max Distance (scale-normalized)')
	p[0].default = 1.0
	p[0].val = 1.0
	p = page.appendFloat('Grabthreshold', label='Grab Threshold')
	p[0].default = 0.6
	p[0].val = 0.6
	p = page.appendToggle('Mirrorx', label='Mirror X Output')
	p[0].default = True
	p[0].val = True
	return


def onPulse(par):
	return


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	hand_active = _state['last_active']  # held between inferences
	hand_x = _state['last_x']
	hand_y = _state['last_y']
	pinch_distance = _state['last_pinch']
	grab_value = 0.0

	try:
		sw = op(SWITCH_PATH)
		# skip the expensive MediaPipe inference entirely while a scene that
		# doesn't need this detector is on screen
		is_active_scene = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
		now = absTime.seconds
		due = (now - _state['last_infer']) >= 1.0 / max(1.0, INFERENCE_HZ)
		if not is_active_scene:
			hand_active = 0.0            # scene not on screen: report no hand, as before
			_state['last_active'] = 0.0
		cam = op(CAM_PATH) if (is_active_scene and due) else None
		if cam is not None:
			_state['last_infer'] = now
			hand_active = 0.0            # this inference decides afresh
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

				if result.hand_landmarks:
					lm = result.hand_landmarks[0]
					wrist = lm[0]
					palm_x = (wrist.x + lm[5].x + lm[9].x + lm[13].x + lm[17].x) / 5.0
					palm_y = (wrist.y + lm[5].y + lm[9].y + lm[13].y + lm[17].y) / 5.0

					thumb_tip = lm[4]
					index_tip = lm[8]
					raw_pinch = ((thumb_tip.x - index_tip.x) ** 2 + (thumb_tip.y - index_tip.y) ** 2) ** 0.5
					hand_scale = ((wrist.x - lm[9].x) ** 2 + (wrist.y - lm[9].y) ** 2) ** 0.5
					pinch_distance = float(raw_pinch / max(hand_scale, 1e-4))

					if scriptOp.par.Mirrorx.eval():
						palm_x = 1.0 - palm_x

					hand_active = 1.0
					hand_x = float(palm_x)
					hand_y = float(palm_y)  # raw mediapipe y: 1=top, 0=bottom (matches project convention)

					_state['last_x'] = hand_x
					_state['last_y'] = hand_y
					_state['last_pinch'] = pinch_distance
				_state['last_active'] = hand_active
	except Exception as e:
		scriptOp.store('last_error', str(e))

	pinch_max = scriptOp.par.Pinchmax.eval()
	if hand_active > 0.5:
		grab_value = max(0.0, min(1.0, 1.0 - (pinch_distance / pinch_max)))
	else:
		grab_value = 0.0

	grab_threshold = scriptOp.par.Grabthreshold.eval()
	grab_active = 1.0 if grab_value >= grab_threshold else 0.0

	for name, val in [
		('hand_active', hand_active),
		('hand_x', hand_x),
		('hand_y', hand_y),
		('pinch_distance', pinch_distance),
		('grab_value', grab_value),
		('grab_active', grab_active),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
