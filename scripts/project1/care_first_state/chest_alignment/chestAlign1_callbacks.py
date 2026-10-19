"""
Script CHOP Callbacks - chest_alignment/chestAlign1

Scores how well the hands' position matches the chest, preferring the
anatomically-grounded PoseLandmarker data (chest_alignment/poseTrack1:
shoulder-midpoint chest + wrist midpoint), which is robust to camera angle
and to the two hands occluding each other. Falls back to the pixel
bounding-box silhouette heuristic if pose tracking has no result this frame.

Outputs:
  chest_x, chest_y        - chest reference position used
  chest_alignment_score   - 0..1, how well the hand/wrist position matches chest
  body_found              - 1.0 if any body reference (pose or silhouette) was found

me - this DAT
scriptOp - the OP which is cooking
"""

from typing import Any
import numpy as np

MASK_PATH = '/project1/care_first_state/chest_alignment/flipMask1'
POSE_PATH = '/project1/care_first_state/chest_alignment/poseTrack1'
HAND_POSE_PATH = '/project1/care_first_state/hand_pose_detection/handPose1'

_state = {
	'last_chest_x': 0.5,
	'last_chest_y': 0.55,
	'using_pose': True,  # which mode is currently latched in
	'pending_mode': None,  # mode we're seeing right now, not yet committed
	'pending_since': None,
}


def onSetupParameters(scriptOp: scriptCHOP):
	page = scriptOp.appendCustomPage('ChestAlign')
	p = page.appendFloat('Chestheightfrac', label='Chest Height Fraction (pixel fallback only)')
	p[0].default = 0.40
	p[0].val = 0.40
	p = page.appendFloat('Alignmenttolerance', label='Alignment Tolerance (fraction of body/shoulder size)')
	p[0].default = 0.35
	p[0].val = 0.35
	p = page.appendFloat('Modeswitchdelay', label='Mode Switch Debounce (s)')
	p[0].default = 0.35
	p[0].val = 0.35
	p[0].normMin = 0.0
	p[0].normMax = 2.0
	return


def onPulse(par: Any):
	return


def onCook(scriptOp: scriptCHOP):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60

	body_found = 0.0
	chest_x = _state['last_chest_x']
	chest_y = _state['last_chest_y']
	chest_align_score = 0.0

	try:
		pose = op(POSE_PATH)
		raw_pose_found = pose['pose_found'].eval() if pose is not None else 0.0
		raw_mode = raw_pose_found > 0.5

		# debounce: only actually switch between pose-tracking and the mask
		# fallback after the new mode has been consistently seen for a bit -
		# pose_found flickers frequently in this setup, and switching modes
		# every frame jumps between two different position estimates, which
		# reads as jitter even though each mode alone is fairly stable
		now = absTime.seconds
		if raw_mode != _state['using_pose']:
			if _state['pending_mode'] != raw_mode:
				_state['pending_mode'] = raw_mode
				_state['pending_since'] = now
			elif now - _state['pending_since'] >= scriptOp.par.Modeswitchdelay.eval():
				_state['using_pose'] = raw_mode
				_state['pending_mode'] = None
		else:
			_state['pending_mode'] = None

		if _state['using_pose']:
			chest_x = pose['chest_x'].eval()
			chest_y = pose['chest_y'].eval()
			body_found = 1.0
			_state['last_chest_x'] = chest_x
			_state['last_chest_y'] = chest_y

			hand_pose = op(HAND_POSE_PATH)
			tol = scriptOp.par.Alignmenttolerance.eval()
			# prefer the hand-landmark position, fall back to pose wrist midpoint
			if hand_pose is not None and hand_pose['hands_present'].eval() > 0.5:
				target_x = hand_pose['pose_x'].eval()
				target_y = hand_pose['pose_y'].eval()
			else:
				target_x = pose['wrist_mid_x'].eval()
				target_y = pose['wrist_mid_y'].eval()

			dx = (target_x - chest_x) / max(tol, 1e-4)
			dy = (target_y - chest_y) / max(tol, 1e-4)
			dist = (dx ** 2 + dy ** 2) ** 0.5
			chest_align_score = max(0.0, min(1.0, 1.0 - dist))
		else:
			mask = op(MASK_PATH)
			if mask is not None:
				arr = mask.numpyArray(delayed=True)
				if arr is not None:
					lum = arr[:, :, 0]
					ys, xs = np.nonzero(lum > 0.5)
					if len(xs) > 50:
						h = arr.shape[0]
						w = arr.shape[1]
						top_row = ys.min()
						bot_row = ys.max()
						left_col = xs.min()
						right_col = xs.max()
						body_height_px = max(bot_row - top_row, 1)

						frac = scriptOp.par.Chestheightfrac.eval()
						chest_row = top_row + frac * body_height_px
						chest_col = (left_col + right_col) / 2.0

						chest_y = float(1.0 - (chest_row / h))
						chest_x = float(chest_col / w)
						body_found = 1.0
						_state['last_chest_x'] = chest_x
						_state['last_chest_y'] = chest_y
	except Exception as e:
		scriptOp.store('last_error', str(e))

	for name, val in [
		('chest_x', chest_x),
		('chest_y', chest_y),
		('chest_alignment_score', chest_align_score),
		('body_found', body_found),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val

	return


def onGetCookLevel(scriptOp: scriptCHOP) -> CookLevel:
	return CookLevel.ALWAYS
