"""
Script CHOP Callbacks - card_sense/act3PhaseState1

Act 3 beat after the card locks: the visitor gets time to look at the card
image and imagine (Imagineseconds). Then the table and slot fade out while
the card's light flies in an arc up into the chest; where it lands, the
Act 2 crack surfaces (kintsugiDraw1) and the self-embrace becomes reachable
(embraceState1). The external ritual object becomes something on the body -
the turn line 9 speaks about.

The landing target is read from kintsugiFollow1's translate, so the light
lands exactly on the crack's centre (one source of truth for chest position).

Act 3 only; resets on entering Act 3 and whenever the card lock clears.

Outputs:
  table_visible   1 -> 0 fade for table / slot / lock ripple
  fly_progress    0..1 eased flight
  flying          1 while in flight
  moved           1 once the flight has started (card light follows card_x/y)
  landed          0/1
  card_x, card_y  card light position (fraction, 1=top)
  card_alpha      card light visibility (fades out right after landing)
  landed_seconds  seconds since landing (0 before)
"""

CARDLOCK_PATH = '/project1/care_third_state/card_sense/cardLockState1'
FOLLOW_PATH = '/project1/care_third_state/card_visual/kintsugiFollow1'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (2,)  # Act 3 only

_state = {'was_active': False, 'prev_locked': False, 'lock_time': None}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Act3Phase')

	def addf(name, label, default, lo, hi):
		p = page.appendFloat(name, label=label)
		p[0].default = default
		p[0].val = default
		p[0].normMin = lo
		p[0].normMax = hi

	addf('Imagineseconds', 'Look / Imagine Time After Lock (s)', 8.0, 0.0, 30.0)
	addf('Tablefadeseconds', 'Table Fade-Out (s)', 2.5, 0.2, 10.0)
	addf('Flyseconds', 'Card Light Flight Duration (s)', 2.5, 0.3, 10.0)
	addf('Archeight', 'Flight Arc Bulge (fraction)', 0.15, 0.0, 0.5)
	addf('Landfadeseconds', 'Card Light Fade On Landing (s)', 0.4, 0.05, 3.0)
	page.appendPulse('Resetphase', label='Reset Phase')
	return


def onPulse(par):
	if par.name == 'Resetphase':
		_state['lock_time'] = None
		_state['prev_locked'] = False
	return


def _clamp01(v):
	return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _smooth(t):
	t = _clamp01(t)
	return t * t * (3.0 - 2.0 * t)


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60
	now = absTime.seconds
	par = scriptOp.par

	sw = op(SWITCH_PATH)
	active = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if active and not _state['was_active']:
		_state['lock_time'] = None
		_state['prev_locked'] = False
	_state['was_active'] = active

	locked = False
	slot_x, slot_y = 0.5, 0.32
	cl = op(CARDLOCK_PATH)
	if active and cl is not None:
		locked = cl['locked'].eval() > 0.5
		slot_x = cl['slot_x'].eval()
		slot_y = cl['slot_y'].eval()
	if locked and not _state['prev_locked']:
		_state['lock_time'] = now
	if not locked:
		_state['lock_time'] = None
	_state['prev_locked'] = locked

	target_x, target_y = 0.5, 0.62
	fol = op(FOLLOW_PATH)
	if fol is not None:
		target_x = fol.par.tx.eval() + 0.5
		target_y = fol.par.ty.eval() + 0.5

	# step 4 (teacher's S3 candle): no chest on screen any more - the card is tossed
	# into the flame on the platform instead and lights it (effect_controller flameIgnite)
	ec = op('/project1/effect_controller')
	candle = ec is not None and ec.par.Uses3candle.eval()
	if candle:
		target_x, target_y = 0.5, 0.37

	table_visible, fly, flying, moved, landed = 1.0, 0.0, 0.0, 0.0, 0.0
	card_x, card_y, card_alpha, landed_s = slot_x, slot_y, 1.0, 0.0

	if _state['lock_time'] is not None:
		t = now - _state['lock_time'] - par.Imagineseconds.eval()
		if t > 0.0:
			fly_dur = max(0.05, par.Flyseconds.eval())
			table_visible = 1.0 - _clamp01(t / max(0.05, par.Tablefadeseconds.eval()))
			fly = _smooth(t / fly_dur)
			moved = 1.0
			flying = 1.0 if t < fly_dur else 0.0
			# quadratic bezier: lob upward, bulging out to one side
			side = 1.0 if target_x >= slot_x else -1.0
			arc = par.Archeight.eval()
			cxp = (slot_x + target_x) / 2.0 + arc * 0.6 * side
			cyp = max(slot_y, target_y) + arc * 0.4
			if candle:
				# slot and flame are almost the same point: lob it up and out, then drop it in
				cxp = (slot_x + target_x) / 2.0 + 0.8 * arc
				cyp = max(slot_y, target_y) + 2.0 * arc
			u = fly
			card_x = (1 - u) ** 2 * slot_x + 2 * (1 - u) * u * cxp + u * u * target_x
			card_y = (1 - u) ** 2 * slot_y + 2 * (1 - u) * u * cyp + u * u * target_y
			if t >= fly_dur:
				landed = 1.0
				landed_s = t - fly_dur
				card_alpha = 1.0 - _clamp01(landed_s / max(0.05, par.Landfadeseconds.eval()))

	for name, val in [
		('table_visible', table_visible),
		('fly_progress', fly),
		('flying', flying),
		('moved', moved),
		('landed', landed),
		('card_x', card_x),
		('card_y', card_y),
		('card_alpha', card_alpha),
		('landed_seconds', landed_s),
	]:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
