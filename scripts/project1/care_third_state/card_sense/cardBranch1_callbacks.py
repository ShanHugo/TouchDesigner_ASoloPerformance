"""
Script CHOP Callbacks - care_third_state/card_sense/cardBranch1

Act 3 branches on which card the visitor drew. TD does not sense the choice:
Unity owns the card table and sends the chosen card as an int OSC message
(default address /CardID, 1-4 for cards A-D; 0 or no message = not drawn yet).
The OSC In CHOP strips the leading slash, so it arrives as a channel named by
the Cardchannel par.

The ONLY thing the branch changes is the candle's colour - the four palettes
live in the editable table cardPalette1, are crossfaded over Blendseconds, and
are read by s3Candle1's uColEdge / uColMid / uColCore / uColLight uniforms.
Card 0 is the pre-draw palette and is pixel-identical to the candle's original
hard-coded warm amber, so nothing changes until a card actually arrives.

Scene-gated like every other act state machine in this project: the card resets
on Act 3 ENTRY (active and not was_active), never at timeline restart.

Outputs:
  card_id          0-4, the card currently driving the colour (latched)
  card_target      0-4, what the selected source says right now
  card_from_unity  1.0 while the id is coming from the OSC channel
  blend            0..1 crossfade progress away from the previous palette
  edge_r/g/b       flame outer colour  -> uColEdge
  mid_r/g/b        flame inner colour  -> uColMid
  core_r/g/b       flame core colour   -> uColCore
  light_r/g/b      cast-light colour   -> uColLight

me - this DAT
scriptOp - the OP which is cooking
"""

OSC_PATH = '/project1/scene_director/oscInFromUnity1'
PALETTE_PATH = '/project1/care_third_state/card_sense/cardPalette1'
SD_PATH = '/project1/scene_director'
SWITCH_PATH = '/project1/scene_director/switchScene1'
ACTIVE_SCENE_INDICES = (2,)  # Act 3 only

ROLES = ('edge', 'mid', 'core', 'light')

_state = {
	'was_active': False,
	'card': 0,
	'from_unity': False,
	'blend_from': None,   # the palette we are crossfading away from
	'blend_start': None,
}


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('CardBranch')
	p = page.appendMenu('Cardsource', label='Where The Card Choice Comes From')
	p[0].menuNames = ['auto', 'unity', 'manual']
	p[0].menuLabels = ['Unity if sending, else manual', 'Unity OSC only', 'Manual only (rehearsal)']
	p[0].default = 'auto'
	p[0].val = 'auto'
	p = page.appendStr('Cardchannel', label='Unity Card Channel Name')
	p[0].default = 'CardID'
	p[0].val = 'CardID'
	p = page.appendFloat('Blendseconds', label='Colour Crossfade (s)')
	p[0].default = 2.5
	p[0].val = 2.5
	p[0].normMin = 0.0
	p[0].normMax = 10.0
	p = page.appendToggle('Holdcard', label='Keep The Card For The Rest Of Act 3')
	p[0].default = True
	p[0].val = True
	p = page.appendPulse('Resetcard', label='Reset To No Card')
	return


def onPulse(par):
	if par.name == 'Resetcard':
		_reset()
	return


def _reset():
	_state['card'] = 0
	_state['from_unity'] = False
	_state['blend_from'] = None
	_state['blend_start'] = None


def _palette(card):
	"""12 floats for a card id, read from the editable cardPalette1 table."""
	tbl = op(PALETTE_PATH)
	fallback = {'edge': (1.0, 0.42, 0.10), 'mid': (1.0, 0.80, 0.45),
	            'core': (1.0, 0.96, 0.88), 'light': (1.0, 0.74, 0.44)}
	if tbl is None or tbl.numRows < 2:
		return fallback
	for r in range(1, tbl.numRows):
		try:
			if int(tbl[r, 'card'].val) != card:
				continue
		except Exception:
			continue
		out = {}
		for role in ROLES:
			try:
				out[role] = (float(tbl[r, role + '_r'].val),
				             float(tbl[r, role + '_g'].val),
				             float(tbl[r, role + '_b'].val))
			except Exception:
				out[role] = fallback[role]
		return out
	return fallback


def _unity_card(scriptOp):
	"""The card id Unity is sending, or None when the channel is absent."""
	osc = op(OSC_PATH)
	if osc is None:
		return None
	name = scriptOp.par.Cardchannel.eval().strip()
	if not name:
		return None
	for c in osc.chans():
		if c.name == name:
			v = int(round(c.eval()))
			return v if 0 <= v <= 4 else None
	return None


def _manual_card():
	sd = op(SD_PATH)
	if sd is None or not hasattr(sd.par, 'Manualcard'):
		return 0
	v = str(sd.par.Manualcard.eval())
	return {'none': 0, 'carda': 1, 'cardb': 2, 'cardc': 3, 'cardd': 4}.get(v, 0)


def onCook(scriptOp):
	scriptOp.clear()
	scriptOp.numSamples = 1
	scriptOp.rate = 60
	now = absTime.seconds

	sw = op(SWITCH_PATH)
	active = sw is None or int(round(sw.par.index.eval())) in ACTIVE_SCENE_INDICES
	if active and not _state['was_active']:
		_reset()
	_state['was_active'] = active

	src = str(scriptOp.par.Cardsource.eval())
	unity = _unity_card(scriptOp)
	manual = _manual_card()
	from_unity = False
	if src == 'unity':
		target = unity if unity is not None else 0
		from_unity = unity is not None and unity > 0
	elif src == 'manual':
		target = manual
	else:  # auto: Unity wins while it is actually sending a drawn card
		if unity is not None and unity > 0:
			target = unity
			from_unity = True
		else:
			target = manual

	# Holdcard: a drawn card stays for the rest of the act even if Unity goes
	# quiet or the rehearsal menu is put back to none.
	if scriptOp.par.Holdcard.eval() and target == 0:
		target = _state['card']

	if target != _state['card']:
		_state["blend_from"] = _blended(scriptOp, now)
		_state['blend_start'] = now
		_state['card'] = target
	_state['from_unity'] = from_unity

	pal, blend = _blended(scriptOp, now, with_progress=True)

	chans = [
		('card_id', float(_state['card'])),
		('card_target', float(target)),
		('card_from_unity', 1.0 if from_unity else 0.0),
		('blend', blend),
	]
	for role in ROLES:
		for i, comp in enumerate('rgb'):
			chans.append((role + '_' + comp, float(pal[role][i])))
	for name, val in chans:
		chan = scriptOp.appendChan(name)
		chan[0] = val
	return


def _blended(scriptOp, now, with_progress=False):
	"""Current palette, crossfading from blend_from over Blendseconds."""
	target = _palette(_state['card'])
	dur = 0.0
	if hasattr(scriptOp.par, "Blendseconds"):
		dur = max(0.0, scriptOp.par.Blendseconds.eval())
	t = 1.0
	if _state['blend_from'] is not None and _state['blend_start'] is not None and dur > 0.0:
		t = max(0.0, min(1.0, (now - _state['blend_start']) / dur))
	if t >= 1.0 or _state['blend_from'] is None:
		return (target, 1.0) if with_progress else target
	out = {}
	for role in ROLES:
		a = _state['blend_from'][role]
		b = target[role]
		out[role] = tuple(a[i] + (b[i] - a[i]) * t for i in range(3))
	return (out, t) if with_progress else out


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
