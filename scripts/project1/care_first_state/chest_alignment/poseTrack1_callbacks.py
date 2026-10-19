"""
Script CHOP Callbacks - chest_alignment/poseTrack1

Runs MediaPipe PoseLandmarker on /project1/bodyGreenFX/cam1 to get an
anatomically-grounded chest reference (shoulder midpoint, camera-angle
invariant, unlike a pixel bounding-box heuristic) and wrist positions.
Pose/skeleton tracking is also more robust than hand-landmark detection
when the two hands occlude each other (e.g. prayer-hands pose), since it
reasons about the whole arm rather than needing to segment two hand blobs.

Outputs:
  pose_found       - 1.0 if a person's pose was detected
  chest_x, chest_y - shoulder midpoint (mirrored/flip-corrected, 1=top)
  wrist_mid_x/y    - midpoint between the two wrists
  wrists_joined    - 0..1, how close the two wrists are (shoulder-width normalized)

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
ACTIVE_SCENE_INDICES = (0, 2)  # needed by Act 1 (chest/ritual) and Act 3 (self-hug ending)
MODEL_PATH = 'C:/Users/Student/Work/TD/models/pose_landmarker_lite.task'
RESIZE_WIDTH = 480
INFERENCE_HZ = 10.0

# Pose landmark indices (MediaPipe Pose 33-point topology)
LEFT_SHOULDER, RIGHT_SHOULDER = 11, 12
LEFT_WRIST, RIGHT_WRIST = 15, 16
LEFT_EYE, RIGHT_EYE = 2, 5

_state = {
	'last_infer': -1e9,
	'last_out': None,
	'last_ts': 0,  # guards MediaPipe VIDEO mode's monotonic-timestamp requirement
	'landmarker': None,
	'last_shoulder_w': 0.25,   # shoulder separation = the body's own unit of measure
	'last_tilt': 0.0,          # shoulder line tilt, in shoulder widths
	'last_head_y': 0.0,        # eye midpoint above the shoulder line, in shoulder widths
	'last_head_x': 0.0,
	'last_chest_x': 0.5,
	'last_chest_y': 0.6,
	'last_wrist_x': 0.5,
	'last_wrist_y': 0.5,
	'debug_lw_ratio': -1.0,
	'debug_rw_ratio': -1.0,
	'debug_lw_conf': -1.0,
	'debug_rw_conf': -1.0,
}


def _get_landmarker():
	if _state['landmarker'] is None:
		options = mp_vision.PoseLandmarkerOptions(
			base_options=BaseOptions(model_asset_path=MODEL_PATH),
			running_mode=mp_vision.RunningMode.VIDEO,
			num_poses=1,
			min_pose_detection_confidence=0.5,
			min_pose_presence_confidence=0.5,
			min_tracking_confidence=0.5,
		)
		_state['landmarker'] = mp_vision.PoseLandmarker.create_from_options(options)
	return _state['landmarker']


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('PoseTrack')
	p = page.appendFloat('Bodyscalesmoothing', label='Body Scale Smoothing (s)')
	p[0].default = 3.0
	p[0].val = 3.0
	p[0].normMin = 0.2
	p[0].normMax = 10.0
	p = page.appendFloat('Wristsjoinedmax', label='Wrists Joined Max Distance (shoulder-width normalized)')
	p[0].default = 0.5
	p[0].val = 0.5
	p[0].normMin = 0.05
	p[0].normMax = 1.5
	p = page.appendToggle('Mirrorx', label='Mirror X Output')
	p[0].default = True
	p[0].val = True
	p = page.appendFloat('Selfhugmax', label='Self-Hug Max Cross Distance (shoulder-width normalized)')
	p[0].default = 0.55
	p[0].val = 0.55
	p[0].normMin = 0.1
	p[0].normMax = 1.5
	p = page.appendFloat('Wristconfidencemin', label='Min Wrist Detection Confidence (both wrists)')
	p[0].default = 0.0
	p[0].val = 0.0
	p[0].normMin = 0.0
	p[0].normMax = 1.0
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

	pose_found = 0.0
	chest_x = _state['last_chest_x']
	chest_y = _state['last_chest_y']
	wrist_mid_x = _state['last_wrist_x']
	wrist_mid_y = _state['last_wrist_y']
	wrists_joined = 0.0
	self_hug_score = 0.0
	eyes_found = 0.0

	try:
		sw = op(SWITCH_PATH)
		# skip the expensive MediaPipe inference entirely while a scene that
		# doesn't need this detector is on screen
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

				mirror_on = scriptOp.par.Mirrorx.eval()

				if result.pose_landmarks:
					lm = result.pose_landmarks[0]
					ls, rs = lm[LEFT_SHOULDER], lm[RIGHT_SHOULDER]
					lw, rw = lm[LEFT_WRIST], lm[RIGHT_WRIST]

					# both wrists must be CONFIDENTLY seen, not just estimated/guessed by
					# the pose model, before any joined-hands/self-hug score can fire -
					# otherwise a single visible hand plus a low-confidence guessed
					# position for the other (occluded/off-camera) wrist can coincidentally
					# land close enough to register as "joined" with only one hand up
					lw_conf = min(getattr(lw, 'visibility', 1.0), getattr(lw, 'presence', 1.0))
					rw_conf = min(getattr(rw, 'visibility', 1.0), getattr(rw, 'presence', 1.0))
					both_wrists_confident = (lw_conf >= scriptOp.par.Wristconfidencemin.eval()
						and rw_conf >= scriptOp.par.Wristconfidencemin.eval())
					_state['debug_lw_conf'] = lw_conf
					_state['debug_rw_conf'] = rw_conf

					shoulder_width = ((ls.x - rs.x) ** 2 + (ls.y - rs.y) ** 2) ** 0.5

					cx = (ls.x + rs.x) / 2.0
					cy = (ls.y + rs.y) / 2.0
					wx = (lw.x + rw.x) / 2.0
					wy = (lw.y + rw.y) / 2.0

					if mirror_on:
						cx = 1.0 - cx
						wx = 1.0 - wx

					pose_found = 1.0
					chest_x = float(cx)
					chest_y = float(cy)  # raw mediapipe y: 1=top, 0=bottom (matches hand_pose_detection convention)
					# unlike chest (shoulders are almost always visible/confident), the
					# wrist landmarks frequently go low-confidence (raised out of frame,
					# occluded, etc) - MediaPipe still returns a value when that happens,
					# but it can be a wild extrapolated guess (seen swinging to -0.8),
					# which downstream consumers (activity/movement tracking) would read
					# as a huge fake "movement" bigger than any real gesture. Freeze at
					# the last confident position instead of passing that through.
					# confidence alone isn't enough - MediaPipe can report a
					# passable confidence score for a wrist it has actually
					# extrapolated wildly off-frame (seen swinging to -0.8), so
					# also sanity-check the position itself is plausible
					wrist_plausible = -0.4 <= wx <= 1.4 and -0.4 <= wy <= 1.4
					if both_wrists_confident and wrist_plausible:
						wrist_mid_x = float(wx)
						wrist_mid_y = float(wy)
					else:
						wrist_mid_x = _state.get('last_wrist_x', 0.5)
						wrist_mid_y = _state.get('last_wrist_y', 0.5)

					wrist_dist = ((lw.x - rw.x) ** 2 + (lw.y - rw.y) ** 2) ** 0.5
					wrist_ratio = wrist_dist / max(shoulder_width, 1e-4)
					wrists_joined_max = scriptOp.par.Wristsjoinedmax.eval()
					wrists_joined = max(0.0, min(1.0, 1.0 - wrist_ratio / wrists_joined_max)) if both_wrists_confident else 0.0

					lw_to_rs = ((lw.x - rs.x) ** 2 + (lw.y - rs.y) ** 2) ** 0.5
					rw_to_ls = ((rw.x - ls.x) ** 2 + (rw.y - ls.y) ** 2) ** 0.5
					selfhug_max = scriptOp.par.Selfhugmax.eval()
					lw_score = max(0.0, min(1.0, 1.0 - (lw_to_rs / max(shoulder_width, 1e-4)) / selfhug_max))
					rw_score = max(0.0, min(1.0, 1.0 - (rw_to_ls / max(shoulder_width, 1e-4)) / selfhug_max))
					self_hug_score = float(min(lw_score, rw_score)) if both_wrists_confident else 0.0
					_state['debug_lw_ratio'] = lw_to_rs / max(shoulder_width, 1e-4)
					_state['debug_rw_ratio'] = rw_to_ls / max(shoulder_width, 1e-4)

					# the body's own scale: everything downstream that asks "how big
					# was that movement" should be measured in these units, not in
					# frame fractions - otherwise standing closer to the camera reads
					# as moving more (artist, 9/30: "我們沒有去定位身體")
					if shoulder_width > 1e-4:
						# smooth it hard: a real body's size does not change from frame
						# to frame, and leaning or turning while raising an arm made the
						# raw shoulder separation jump 36% - which, as the denominator,
						# made the BIGGEST gesture measure smaller than a medium one
						sw_prev = _state.get('last_shoulder_w') or float(shoulder_width)
						tau = max(0.1, scriptOp.par.Bodyscalesmoothing.eval()) if hasattr(scriptOp.par, 'Bodyscalesmoothing') else 3.0
						k = min(1.0, (1.0 / max(1.0, INFERENCE_HZ)) / tau)
						_state['last_shoulder_w'] = sw_prev + (float(shoulder_width) - sw_prev) * k
					_state['last_chest_x'] = chest_x
					_state['last_chest_y'] = chest_y
					_state['last_wrist_x'] = wrist_mid_x
					_state['last_wrist_y'] = wrist_mid_y

					# upper-body signals for the heartbeat: with the hands out of
					# frame, the shoulder line and the head are the only things
					# tracked reliably. Both expressed in shoulder widths.
					_sw = max(1e-4, shoulder_width)
					_mirror = bool(scriptOp.par.Mirrorx.eval())
					_tilt = (ls.y - rs.y) / _sw
					if _mirror:
						_tilt = -_tilt
					_state['last_tilt'] = float(_tilt)

					le, re = lm[LEFT_EYE], lm[RIGHT_EYE]
					le_conf = min(getattr(le, 'visibility', 1.0), getattr(le, 'presence', 1.0))
					re_conf = min(getattr(re, 'visibility', 1.0), getattr(re, 'presence', 1.0))
					eyes_found = 1.0 if (le_conf > 0.5 and re_conf > 0.5) else 0.0
					if eyes_found > 0.5:
						_ex = (le.x + re.x) / 2.0
						_ey = (le.y + re.y) / 2.0
						if _mirror:
							_ex = 1.0 - _ex
						# chest_x/chest_y are already mirror-corrected at this point,
						# so compare in that same space
						_state['last_head_x'] = float((_ex - chest_x) / _sw)
						_state['last_head_y'] = float((_ey - chest_y) / _sw)
	except Exception as e:
		scriptOp.store('last_error', str(e))

	body_scale = max(1e-4, _state.get('last_shoulder_w', 0.25))
	wrist_rel_y = (wrist_mid_y - chest_y) / body_scale
	wrist_rel_x = (wrist_mid_x - chest_x) / body_scale

	for name, val in [
		('pose_found', pose_found),
		('chest_x', chest_x),
		('chest_y', chest_y),
		('wrist_mid_x', wrist_mid_x),
		('wrist_mid_y', wrist_mid_y),
		('body_scale', body_scale),
		('wrist_rel_y', wrist_rel_y),
		('wrist_rel_x', wrist_rel_x),
		('shoulder_tilt', _state.get('last_tilt', 0.0)),
		('head_rel_y', _state.get('last_head_y', 0.0)),
		('head_rel_x', _state.get('last_head_x', 0.0)),
		('chest_rel_x', chest_x / body_scale),
		('chest_rel_y', chest_y / body_scale),
		('wrists_joined', wrists_joined),
		('self_hug_score', self_hug_score),
		('debug_lw_ratio', _state['debug_lw_ratio']),
		('debug_rw_ratio', _state['debug_rw_ratio']),
		('debug_lw_conf', _state['debug_lw_conf']),
		('debug_rw_conf', _state['debug_rw_conf']),
		('eyes_found', eyes_found),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	_state['last_out'] = [(c.name, c[0]) for c in scriptOp.chans()]
	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
