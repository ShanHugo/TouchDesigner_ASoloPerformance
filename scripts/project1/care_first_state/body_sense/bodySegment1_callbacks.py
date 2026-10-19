"""
Script TOP Callbacks - body_sense/bodySegment1

Runs MediaPipe ImageSegmenter (selfie segmentation) on /project1/bodyGreenFX/cam1
to produce a true person-vs-background mask - an actual neural network trained
to recognize human shapes, unlike the background-difference heuristic in
bodyGreenFX/silhouette1 (which just flags "different from a stored snapshot"
and needs periodic recalibration, breaks on lighting/camera changes, etc).

Outputs a white=person / black=background RGBA mask, same 1280x720 canvas and
mirror convention as bodyGreenFX (mirrored horizontally to match hand tracking).

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
MODEL_PATH = 'C:/Users/Student/Work/TD/models/selfie_segmenter.tflite'
RESIZE_WIDTH = 320
OUT_W, OUT_H = 640, 360  # the mask is blurred, thresholded and edge-detected downstream,
                          # so a quarter-size mask is visually identical and cuts both the
                          # cv2.resize and the per-inference texture upload by 4x
# Segmentation does not need a fresh inference every frame: the body barely moves
# between frames, and this was costing ~43ms of CPU + ~50ms of GPU upload EVERY
# frame, which is what starved the rest of the pipeline. Between inferences the
# previous mask texture simply stays in place.
INFERENCE_HZ = 10.0

_state = {
	'last_infer': -1e9,
	'last_ts': 0,  # guards MediaPipe VIDEO mode's monotonic-timestamp requirement
	'segmenter': None,
}


def _get_segmenter():
	if _state['segmenter'] is None:
		options = mp_vision.ImageSegmenterOptions(
			base_options=BaseOptions(model_asset_path=MODEL_PATH),
			running_mode=mp_vision.RunningMode.VIDEO,
			output_category_mask=True,
		)
		_state['segmenter'] = mp_vision.ImageSegmenter.create_from_options(options)
	return _state['segmenter']


def onSetupParameters(scriptOp: scriptTOP):
	page = scriptOp.appendCustomPage('BodySegment')
	p = page.appendToggle('Mirrorx', label='Mirror X Output')
	p[0].default = True
	p[0].val = True
	return


def onPulse(par):
	return


def onCook(scriptOp: scriptTOP):
	# NVIDIA Background (GPU) now supplies the mask via body_sense/maskSource1; while it is selected
	# this CPU MediaPipe model is only the fallback, so skip inference entirely (keep last texture)
	ec = op('/project1/effect_controller')
	if ec is not None and ec.par.Usegpumask.eval():
		return
	now = absTime.seconds
	if now - _state['last_infer'] < 1.0 / max(1.0, INFERENCE_HZ):
		return  # not due yet - keep the previous mask texture, cost zero
	_state['last_infer'] = now

	canvas = np.zeros((OUT_H, OUT_W, 4), dtype=np.uint8)

	try:
		cam = op(CAM_PATH)
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
				segmenter = _get_segmenter()
				timestamp_ms = int(absTime.seconds * 1000)
				if timestamp_ms <= _state['last_ts']:
					# MediaPipe VIDEO mode requires strictly increasing timestamps;
					# int(ms) truncation can repeat the same value on back-to-back
					# cooks, which used to throw and silently blank the whole frame
					timestamp_ms = _state['last_ts'] + 1
				_state['last_ts'] = timestamp_ms
				result = segmenter.segment_for_video(mp_image, timestamp_ms)

				if result.category_mask is not None:
					mask = result.category_mask.numpy_view()
					mask_bool = mask.astype(np.float32) < 0.5
					mask255 = mask_bool.astype(np.uint8) * np.uint8(255)
					mask_resized = cv2.resize(mask255, (OUT_W, OUT_H), interpolation=cv2.INTER_NEAREST)

					if scriptOp.par.Mirrorx.eval():
						mask_resized = np.fliplr(mask_resized)

					canvas[:, :, 0] = mask_resized
					canvas[:, :, 1] = mask_resized
					canvas[:, :, 2] = mask_resized
					canvas[:, :, 3] = 255
	except Exception as e:
		scriptOp.store('last_error', str(e))

	scriptOp.copyNumpyArray(canvas)
	return


def onGetCookLevel(scriptOp: scriptTOP) -> CookLevel:
	return CookLevel.ALWAYS
