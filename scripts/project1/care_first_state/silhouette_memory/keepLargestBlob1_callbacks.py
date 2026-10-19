"""
Script TOP Callbacks - silhouette_memory/keepLargestBlob1

The selfie-segmentation model sometimes misclassifies a chunk of
background as "person" - not as fine speckle noise (a blur+rethreshold
despeckle doesn't touch it) but as a genuinely separate, disconnected
blob of real size. This keeps only the LARGEST connected white region
in the mask and blacks out everything else, which is exactly what a
stray background misdetection looks like: same-ish white value, but
not actually touching the real person shape.

me - this OP
scriptOp - the OP which is cooking
"""

import numpy as np
import cv2


SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (0,)  # Act 1 only: this mask feeds silhouette_memory, and
                              # nothing outside Act 1 consumes that COMP's output

DOWNSCALE = 8  # run connected-components on a much smaller mask - which
                # blob is largest doesn't change at lower resolution, and
                # this cuts the cost by DOWNSCALE**2 (~64x at 8)


def onCook(scriptOp):
	# Outside Act 1 this cost 22ms of CPU per frame for an image nobody displays,
	# and its blocking readback stalled the GPU pipeline as well. Returning without
	# copying leaves the previous texture in place: no cost, and (unlike writing a
	# small blank) no resolution collapse in the composites downstream.
	# the GPU path (blobDown1 -> blobPick1 -> blobUp1 -> blobApply1) replaces this
	# node; switch it off here as well, or it keeps doing the full-resolution
	# readback for an image blobSwitch1 is no longer selecting
	smc = op('/project1/care_first_state/silhouette_memory')
	if smc is not None and hasattr(smc.par, 'Usegpublob') and smc.par.Usegpublob.eval():
		return

	sw = op(SWITCH_PATH)
	if not (sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES):
		return

	inp = scriptOp.inputs[0] if scriptOp.inputs else None
	if inp is None:
		return
	# delayed=True: a one-frame-old silhouette is invisible in a memory trail, and it
	# avoids blocking the GPU while the frame is copied back to system memory
	arr = inp.numpyArray(delayed=True)
	if arr is None:
		return

	h, w = arr.shape[0], arr.shape[1]
	small_w, small_h = max(8, w // DOWNSCALE), max(8, h // DOWNSCALE)
	mask_full = (arr[:, :, 0] > 0.5).astype(np.uint8)
	mask_small = cv2.resize(mask_full, (small_w, small_h), interpolation=cv2.INTER_NEAREST)

	num_labels, labels_small, stats, _ = cv2.connectedComponentsWithStats(mask_small, connectivity=8)

	out = arr.copy()
	if num_labels > 1:
		areas = stats[1:, cv2.CC_STAT_AREA]
		largest_label = 1 + int(np.argmax(areas))
		keep_small = (labels_small == largest_label).astype(np.uint8)
		# The small grid only decides WHICH blob to keep. Grown by one cell before the
		# nearest-neighbour upscale so it fully covers that blob: the outline then
		# comes from the full-resolution mask. Without this the 8x8 blocks cut into the
		# edge and the Act 1 silhouette showed 16px stair-steps at 1280x720.
		keep_small = cv2.dilate(keep_small, np.ones((3, 3), np.uint8), iterations=1)
		keep = cv2.resize(keep_small, (w, h), interpolation=cv2.INTER_NEAREST).astype(bool)
		for ch in range(out.shape[2]):
			out[:, :, ch] = out[:, :, ch] * keep
	else:
		out[:] = 0

	scriptOp.copyNumpyArray(out.astype(np.float32))
	return

