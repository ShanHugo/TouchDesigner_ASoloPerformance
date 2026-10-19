"""
Script TOP Callbacks - silhouette_memory/blobPick1

The CPU half of keepLargestBlob1, and nothing else. Deciding WHICH connected
blob is the person genuinely needs OpenCV, but it never needed the full frame:
the old node read 640x360 back from the GPU, thresholded and copied it, masked
every channel and uploaded 640x360 again, all to apply a decision it had
already made on an 8x-downscaled grid.

Here blobDown1 does the downscale on the GPU (nearest, so it point-samples
exactly like the old cv2.INTER_NEAREST did), this script reads back only
80x45 - 64x less data - and outputs just the keep mask. blobUp1 scales that
back up (nearest again) and blobApply1 multiplies the ORIGINAL full-resolution
mask by it, so the silhouette's outline still comes from full resolution
exactly as before; only the decision travels through the small grid.

Dilated by one cell before it leaves, same as the old code: without it the 8x8
blocks cut into the blob's edge after the nearest upscale and the Act 1
silhouette showed 16px stair-steps.

me - this OP
scriptOp - the OP which is cooking
"""

import numpy as np
import cv2

SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (0,)  # Act 1 only - nothing else consumes silhouette_memory


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Blob')
	p = page.appendFloat('Cellcoverage', label='Cell Counts As Person Above')
	p[0].default = 0.15
	p[0].val = 0.15
	p[0].normMin = 0.02
	p[0].normMax = 0.9
	return


def onCook(scriptOp):
	sw = op(SWITCH_PATH)
	if not (sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES):
		# leave the previous texture in place; writing a blank would collapse the
		# resolution for everything downstream
		return

	inp = scriptOp.inputs[0] if scriptOp.inputs else None
	if inp is None:
		return
	# delayed=True: a one-frame-old silhouette is invisible in a memory trail and
	# it keeps the readback from blocking the GPU
	arr = inp.numpyArray(delayed=True)
	if arr is None:
		return

	h, w = arr.shape[0], arr.shape[1]
	# blobDown1 downscales with MIPMAP, so each cell holds the FRACTION of its
	# 8x8 full-res pixels that are person, not one point sample. Thresholding
	# that low means a cell counts as person if any real part of the body falls
	# in it - which is what keeps thin links (a neck, an arm against the torso)
	# connected. Point sampling broke them: it cut the head off the shoulders
	# along an 8px block edge whenever the link happened to miss the sample point.
	cov = scriptOp.par.Cellcoverage.eval() if hasattr(scriptOp.par, 'Cellcoverage') else 0.15
	mask = (arr[:, :, 0] > cov).astype(np.uint8)
	keep = np.zeros((h, w), dtype=np.float32)

	num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
	if num_labels > 1:
		areas = stats[1:, cv2.CC_STAT_AREA]
		largest = 1 + int(np.argmax(areas))
		k = (labels == largest).astype(np.uint8)
		k = cv2.dilate(k, np.ones((3, 3), np.uint8), iterations=1)
		keep = k.astype(np.float32)

	scriptOp.copyNumpyArray(np.repeat(keep[:, :, None], 4, axis=2))
	return
