"""
Script TOP Callbacks - scene_director/verticalType1

Step 1 of the teacher's visual plan (TD視覺風格設定.docx, "台詞排版規則（共通）"):
the dialogue is "the second performer in the frame", not a subtitle bar.
  - white serif (Noto Serif TC), NO outline / glow / shadow
  - vertical, split into 1-3 columns (read right to left), each later column
	starting a little lower (staggered)
  - small when calm; only the KEYWORDS grow as the act's emotion rises
	(effect_controller: S1 bloomStrength, S2 sceneHeat, S3 flameGain)
  - revealed character by character with a pause between columns, faster at
	the outburst (S2 heat past Burstheat)
  - placed per line in a reading area (left / right third), from the editable
	table verticalTypeLayout1: act | line | text ('|' = column break) |
	keywords (',' separated) | x (centre of the FIRST, rightmost column, 0-1) |
	y (top, 0-1 from the top) | size (px at 1280x720)
Lines missing from the table fall back to currentLineText1, split at punctuation.

Cost: the glyph layer is only re-drawn when the line, the layout or the keyword
scale changes; per frame only a per-character alpha lookup runs, and nothing is
uploaded once every visible character has fully faded in.
"""

import math
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LAYOUT_PATH = '/project1/scene_director/verticalTypeLayout1'
LINE_PATH = '/project1/scene_director/lineTrack1'
TEXT_PATH = '/project1/scene_director/currentLineText1'
EFFECT_PATH = '/project1/effect_controller/effectOut1'
EMOTION_CHAN = {1: 'bloomStrength', 2: 'sceneHeat', 3: 'flameGain'}

# horizontal punctuation -> vertical presentation forms (all present in Noto Serif TC)
VERTICAL_FORMS = {'，': '︐', '。': '︒', '、': '︑', '！': '︕', '？': '︖', '：': '︓',
				  '；': '︔', '「': '﹁', '」': '﹂', '『': '﹃', '』': '﹄', '（': '︵',
				  '）': '︶', '—': '︱', '…': '︙', '!': '︕', '?': '︖', ',': '︐'}
BREAK_AFTER = set('，。！？；…')

_state = {
	'glyphs': [],'key': None, 'reveal': 0.0, 'last_time': None, 'layout_sig': None,
		  'layer': None, 'index': None, 'starts': [], 'n': 0, 'done': False,
		  'fonts': {}, 'blank_sent': False, 'box': None, 'buf': None}


def _font_path(scriptOp):
	"""Fontpath may be relative so the project is portable. PIL resolves a
	relative path against the PROCESS working directory - which is TD's install
	folder, not this .toe's folder - so expand it here against the project.
	A path starting with a drive letter is used as given."""
	p = scriptOp.par.Fontpath.eval().strip()
	if not p:
		return p
	if os.path.isabs(p):
		return p
	return os.path.join(project.folder, p).replace('\\', '/')


def _font(scriptOp, size):
	size = max(8, int(round(size)))
	k = (_font_path(scriptOp), scriptOp.par.Fontweight.eval(), size)
	f = _state['fonts'].get(k)
	if f is None:
		f = ImageFont.truetype(k[0], size)
		try:
			f.set_variation_by_name(k[1])
		except Exception:
			pass
		_state['fonts'][k] = f
	return f


def _vertical_chars(text):
	text = text.replace('......', '…').replace('...', '…').replace('……', '…')
	return [VERTICAL_FORMS.get(ch, ch) for ch in text if ch not in ' 　']


def _auto_columns(text):
	# fallback when a line is not in the table: break after punctuation into <= 3 columns
	parts, cur = [], ''
	for ch in text:
		cur += ch
		if ch in BREAK_AFTER and len(cur) >= 6:
			parts.append(cur); cur = ''
	if cur:
		parts.append(cur)
	while len(parts) > 3:
		i = min(range(len(parts) - 1), key=lambda j: len(parts[j]) + len(parts[j + 1]))
		parts[i:i + 2] = [parts[i] + parts[i + 1]]
	return parts


def line_spec(act, line):
	"""(columns, keywords, x, y, size) for this line"""
	t = op(LAYOUT_PATH)
	if t is not None:
		for r in range(1, t.numRows):
			try:
				if int(t[r, 'act'].val) == act and int(t[r, 'line'].val) == line:
					return ([c for c in t[r, 'text'].val.split('|') if c],
							[k for k in t[r, 'keywords'].val.split(',') if k],
							float(t[r, 'x'].val), float(t[r, 'y'].val), float(t[r, 'size'].val))
			except Exception:
				continue
	txt = op(TEXT_PATH).text.strip() if op(TEXT_PATH) is not None else ''
	return (_auto_columns(txt), [], 0.86, 0.12, 30.0) if txt else ([], [], 0.86, 0.12, 30.0)


def build_layer(scriptOp, spec, kw_scale, w, h):
	"""draw every character at full alpha; returns (layer, index_map, starts, n)"""
	columns, keywords, x, y, size = spec
	par = scriptOp.par
	size *= par.Sizemul.eval()
	img = Image.new('L', (w, h), 0)
	draw = ImageDraw.Draw(img)
	index = np.full((h, w), -1, dtype=np.int32)
	starts, n, units = [], 0, 0.0
	glyphs = []          # (char, x, baseline_y, size, index) for the animated redraw
	col_x = x * w
	prev_half = None
	jit_t = par.Timingjitter.eval() if hasattr(par, 'Timingjitter') else 0.0
	jit_s = par.Sizejitter.eval() if hasattr(par, 'Sizejitter') else 0.0
	seed = hash((tuple(columns), round(size, 2))) & 0xffff
	for ci, col in enumerate(columns):
		chars = _vertical_chars(col)
		# which characters belong to a keyword (matched on the original text)
		flat = col.replace('......', '…').replace('...', '…').replace('……', '…').replace(' ', '')
		kw_mask = [False] * len(flat)
		for kw in keywords:
			p = flat.find(kw)
			while p >= 0:
				for j in range(p, p + len(kw)):
					kw_mask[j] = True
				p = flat.find(kw, p + 1)
		sizes = [size * (kw_scale if (i < len(kw_mask) and kw_mask[i]) else 1.0) for i in range(len(chars))]
		# 大小錯落: a deterministic wobble per character (identical on every rebuild,
		# so the line does not shimmer when the layout is re-triggered)
		if jit_s > 0.0:
			sizes = [round(s * (1.0 + jit_s * (((seed + ci * 131 + i * 37) % 1000) / 500.0 - 1.0)) * 2.0) / 2.0
					 for i, s in enumerate(sizes)]
		half = max(sizes) / 2.0 if sizes else size / 2.0
		if prev_half is not None:
			col_x -= prev_half + half + size * par.Columngap.eval()
		prev_half = half
		cy = y * h + ci * size * par.Stagger.eval()
		for ch, s in zip(chars, sizes):
			f = _font(scriptOp, s)
			cell = s * par.Leading.eval()
			left, top = int(col_x - s / 2), int(cy)
			baseline_y = cy + 0.88 * s + (cell - s) / 2.0
			draw.text((col_x - s / 2.0, baseline_y), ch, font=f, fill=255, anchor='ls')
			index[max(0, top):max(0, min(h, int(cy + cell))), max(0, left):max(0, min(w, int(col_x + s / 2.0) + 1))] = n
			# 出現的時序跳動: every character waits its own slightly different beat
			wob = (((seed + n * 71) % 1000) / 1000.0) * jit_t
			starts.append(units + wob)
			glyphs.append((ch, col_x - s / 2.0, baseline_y, s, n))
			units += 1.0
			n += 1
			cy += cell
		units += par.Columnpause.eval() * par.Charspersecond.eval()
	layer = np.flipud(np.asarray(img, dtype=np.float32) / 255.0)
	index = np.flipud(index)
	# only the text's bounding box is processed per frame (usually < 10% of the frame)
	rows = np.where((index >= 0).any(axis=1))[0]
	cols = np.where((index >= 0).any(axis=0))[0]
	if rows.size == 0:
		return layer[:1, :1].copy(), index[:1, :1].copy(), (0, 1, 0, 1), starts, n
	box = (int(rows[0]), int(rows[-1]) + 1, int(cols[0]), int(cols[-1]) + 1)
	y0, y1, x0, x1 = box
	_state['glyphs'] = glyphs
	return layer[y0:y1, x0:x1].copy(), index[y0:y1, x0:x1].copy(), box, starts, n


def draw_inflight(scriptOp, box, reveal, starts, fade_units):
	# Only the handful of characters that are still falling get redrawn; everything
	# already seated comes from the baked layer through the LUT, as before. Redrawing
	# the whole line every frame cost 184 ms (~5 fps) - this costs a few glyph draws
	# into the text's own bounding box.
	par = scriptOp.par
	glyphs = _state.get('glyphs') or []
	drop_h = par.Dropheight.eval()
	drop_u = max(0.05, par.Dropseconds.eval() * par.Charspersecond.eval())
	bounce = par.Dropbounce.eval()
	y0, y1, x0, x1 = box
	img = Image.new('L', (x1 - x0, y1 - y0), 0)
	draw = ImageDraw.Draw(img)
	moving = []
	any_drawn = False
	for (ch, gx, gy, s, idx) in glyphs:
		t0 = starts[idx] if idx < len(starts) else 0.0
		a = (reveal - t0) / fade_units
		if a <= 0.0:
			continue
		d = (reveal - t0) / drop_u
		if d >= 1.0:
			continue                       # landed: the baked layer covers it
		moving.append(idx)
		e = 1.0 - (1.0 - max(0.0, d)) ** 3
		off = -drop_h * s * (1.0 - e)
		if bounce > 0.0:
			off += bounce * s * (1.0 - d) * math.sin(d * math.pi * 2.0)
		f = _font(scriptOp, s)
		draw.text((gx - x0, gy + off - y0), ch, font=f,
				  fill=int(round(min(1.0, a) * 255)), anchor='ls')
		any_drawn = True
	if not any_drawn:
		return None, moving
	return np.flipud(np.asarray(img, dtype=np.uint8)), moving


def draw_falling(scriptOp, w, h, reveal, starts, fade_units):
	# 掉落感: while the line is still arriving, each character is drawn at its own
	# offset above its final seat and eased down into place. A baked layer cannot
	# move one character on its own, so the animating frames are redrawn glyph by
	# glyph; once the last one lands, onCook switches back to the cheap baked path.
	par = scriptOp.par
	glyphs = _state.get('glyphs') or []
	drop_h = par.Dropheight.eval() if hasattr(par, 'Dropheight') else 0.0
	drop_u = max(0.05, (par.Dropseconds.eval() if hasattr(par, 'Dropseconds') else 0.4)
				 * par.Charspersecond.eval())
	bounce = par.Dropbounce.eval() if hasattr(par, 'Dropbounce') else 0.0
	img = Image.new('L', (w, h), 0)
	draw = ImageDraw.Draw(img)
	landed = True
	for (ch, gx, gy, s, idx) in glyphs:
		t0 = starts[idx] if idx < len(starts) else 0.0
		a = (reveal - t0) / fade_units
		if a <= 0.0:
			landed = False
			continue
		d = min(1.0, max(0.0, (reveal - t0) / drop_u))
		if d < 1.0:
			landed = False
		e = 1.0 - (1.0 - d) ** 3                      # ease-out
		off = -drop_h * s * (1.0 - e)
		if bounce > 0.0 and 0.0 < d < 1.0:
			off += bounce * s * (1.0 - d) * math.sin(d * math.pi * 2.0)
		f = _font(scriptOp, s)
		draw.text((gx, gy + off), ch, font=f, fill=int(round(min(1.0, a) * 255)), anchor='ls')
	return np.flipud(np.asarray(img, dtype=np.uint8)), landed


def onSetupParameters(scriptOp):
	page = scriptOp.appendCustomPage('Typography')
	p = page.appendToggle('Useverticaltype', label='Use Vertical Typography (off = old subtitle)')
	p[0].default = True; p[0].val = True
	p = page.appendFile('Fontpath', label='Font File')
	p[0].default = 'C:/Windows/Fonts/NotoSerifTC-VF.ttf'; p[0].val = p[0].default
	p = page.appendStr('Fontweight', label='Font Weight (variable font style name)')
	p[0].default = 'Regular'; p[0].val = 'Regular'
	for name, label, val in (
			('Sizemul', 'Size Multiplier', 1.0),
			('Leading', 'Character Spacing (x size)', 1.12),
			('Columngap', 'Column Gap (x size)', 0.7),
			('Stagger', 'Column Stagger Down (x size)', 1.2),
			('Charspersecond', 'Reveal Speed (chars/s)', 5.0),
			('Columnpause', 'Pause Between Columns (s)', 0.6),
			('Fadeseconds', 'Per-Character Fade In (s)', 0.35),
			('Keywordboost', 'Keyword Growth At Full Emotion', 0.6),
			('Burstheat', 'S2 Heat That Counts As The Outburst', 0.75),
			('Burstspeedup', 'Reveal Speed-up At The Outburst', 2.5)):
		p = page.appendFloat(name, label=label)
		p[0].default = val; p[0].val = val
	return


def _emotion(act):
	try:
		e = op(EFFECT_PATH)
		c = e[EMOTION_CHAN.get(act, 'bloomStrength')] if e is not None else None
		v = c.eval() if c is not None else None
		return 0.0 if v is None else float(v)
	except Exception:
		return 0.0


def onCook(scriptOp):
	par = scriptOp.par
	w, h = int(par.resolutionw.eval()), int(par.resolutionh.eval())
	if not par.Useverticaltype.eval():
		return
	now = absTime.seconds
	dt = 0.0 if _state['last_time'] is None else max(0.0, min(0.5, now - _state['last_time']))
	_state['last_time'] = now

	lt = op(LINE_PATH)
	try:
		act = int(round(lt['td_act'].eval())); line = int(round(lt['td_line'].eval()))
	except Exception:
		act, line = 0, 0
	key = (act, line)
	if key != _state['key']:
		_state.update({'key': key, 'reveal': 0.0, 'layout_sig': None, 'done': False})

	spec = line_spec(act, line) if act > 0 and line > 0 else ([], [], 0, 0, 0)
	if not spec[0]:
		if not _state['blank_sent']:
			scriptOp.copyNumpyArray(np.zeros((h, w, 4), dtype=np.uint8))
			_state['blank_sent'] = True
		return
	_state['blank_sent'] = False

	emotion = _emotion(act)
	kw_scale = 1.0 + par.Keywordboost.eval() * max(0.0, min(1.0, emotion))
	kw_scale = round(kw_scale / 0.02) * 0.02
	try:
		e = op(EFFECT_PATH)
		tscale = float(e['textScale'].eval()); tox = float(e['textOffsetx'].eval()); toy = float(e['textOffsety'].eval())
	except Exception:
		tscale, tox, toy = 1.0, 0.0, 0.0
	spec = (spec[0], spec[1], spec[2] + tox, spec[3] + toy, spec[4] * tscale)
	sig = (spec, kw_scale, w, h, par.Fontweight.eval(), par.Sizemul.eval(), par.Leading.eval(),
		   par.Columngap.eval(), par.Stagger.eval(), par.Columnpause.eval(), par.Charspersecond.eval())
	rebuilt = False
	if sig != _state['layout_sig']:
		_state['layer'], _state['index'], _state['box'], _state['starts'], _state['n'] = build_layer(scriptOp, spec, kw_scale, w, h)
		_state['buf'] = np.zeros((h, w, 4), dtype=np.uint8)  # persistent 8-bit frame, text box written into it
		_state['layout_sig'] = sig
		rebuilt = True

	speed = par.Burstspeedup.eval() if (act == 2 and emotion >= par.Burstheat.eval()) else 1.0
	_state['reveal'] += dt * par.Charspersecond.eval() * speed
	fade_units = max(0.01, par.Fadeseconds.eval() * par.Charspersecond.eval())
	starts = np.asarray(_state['starts'], dtype=np.float32)
	alphas = np.clip((_state['reveal'] - starts) / fade_units, 0.0, 1.0)
	done = bool(alphas.size) and bool(alphas.min() >= 1.0)
	if done and _state['done'] and not rebuilt:
		return  # fully shown and unchanged: keep the last upload, cost nothing
	_state['done'] = done
	# While characters are still falling into place they each need their own
	# position, which a single baked layer cannot express - redraw glyph by glyph
	# for those frames only, then fall back to the cheap LUT path once everything
	# has landed (typography is where the effort goes now, per the 10/06 note).
	drop_h = par.Dropheight.eval() if hasattr(par, 'Dropheight') else 0.0
	inflight = None
	if drop_h > 0.0 and not done:
		drop_u = max(0.05, par.Dropseconds.eval() * par.Charspersecond.eval())
		prog = (_state['reveal'] - starts) / drop_u
		moving_mask = (prog > 0.0) & (prog < 1.0)
		if moving_mask.any():
			inflight, _ = draw_inflight(scriptOp, _state['box'], _state['reveal'],
										_state['starts'], fade_units)
			alphas = np.where(moving_mask, 0.0, alphas)   # the baked copy must not
			                                              # show while it is in flight

	lut = np.concatenate([[0.0], alphas]).astype(np.float32)
	a8 = (_state['layer'] * lut[_state['index'] + 1] * 255.0 + 0.5).astype(np.uint8)
	if inflight is not None:
		a8 = np.maximum(a8, inflight)
	y0, y1, x0, x1 = _state['box']
	_state['buf'][:, :, :] = 0
	_state['buf'][y0:y1, x0:x1, :] = a8[..., None]
	scriptOp.copyNumpyArray(_state['buf'])
	return


def onGetCookLevel(scriptOp):
	return CookLevel.ALWAYS
