"""Regenerate the readable scripts/ tree from an expanded .toe.

Why this exists
---------------
Effect.toe is binary, so git can store it but can never show you WHAT changed.
Every piece of logic in this project lives in Python/GLSL Text DATs, so those
are extracted to real .py/.glsl files that git can diff line by line.

Usage (from the TD project folder, with TouchDesigner closed):

    "C:/Program Files/Derivative/TouchDesigner/bin/toeexpand.exe" Effect.toe
    "C:/Program Files/Derivative/TouchDesigner/bin/python.exe" -I tools/export_scripts.py

Effect.toe stays the source of truth. scripts/ is generated output - never
edit it and expect TouchDesigner to notice.

File formats (worked out by inspection; both checks below are self-verifying,
which matters because a fixed offset silently ate the first character of
short files)
------------
*.text   <binary header><uint16 BE length><utf-8 body>
         The length's high byte is often 0x00, so it looks like part of the
         header. Locate it by the only reliable property: the declared length
         must equal the number of bytes that actually follow it.

*.table  <'1' NL '*'><u32 ver><u32 rows><u32 cols><u32 pad>
         then rows*cols cells, each <u32 tag><u32 len><utf-8 bytes>.
         Verified by requiring the cells to come out exactly rows*cols AND to
         consume the file to its final byte.
"""

import ast
import glob
import os
import struct

SRC = 'Effect.toe.dir'
DST = 'scripts'
GLSL_HINTS = ('_pixel', '_vertex', '_geometry', '_compute')


def be32(b, o):
    return struct.unpack('>I', b[o:o + 4])[0]


def text_payload(path):
    b = open(path, 'rb').read()
    for k in range(0, 64):
        if k + 2 > len(b):
            break
        if b[k] * 256 + b[k + 1] == len(b) - k - 2:
            return b[k + 2:].decode('utf-8')
    return None


def table_grid(path):
    b = open(path, 'rb').read()
    rows, cols = be32(b, 7), be32(b, 11)
    o, cells = 19, []
    for _ in range(rows * cols):
        if o + 8 > len(b):
            return None
        n = be32(b, o + 4)
        cells.append(b[o + 8: o + 8 + n].decode('utf-8'))
        o += 8 + n
    if o != len(b):
        return None
    return [cells[r * cols:(r + 1) * cols] for r in range(rows)]


def write(rel_base, ext, body):
    dest = os.path.join(DST, rel_base + '.' + ext)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(body)


def main():
    if not os.path.isdir(SRC):
        raise SystemExit('run toeexpand first - %s not found' % SRC)

    counts = {'py': 0, 'glsl': 0, 'txt': 0, 'tsv': 0, 'empty': 0}
    failed = []

    for f in glob.glob(os.path.join(SRC, '**', '*.text'), recursive=True):
        try:
            body = text_payload(f)
        except UnicodeDecodeError:
            body = None
        if body is None:
            failed.append(f)
            continue
        if not body.strip():
            counts['empty'] += 1
            continue
        rel = os.path.relpath(f, SRC).replace(os.sep, '/')[:-5]
        name = rel.split('/')[-1]
        if any(h in name for h in GLSL_HINTS):
            kind = 'glsl'
        else:
            try:
                ast.parse(body)
                kind = 'py'
            except SyntaxError:
                kind = 'txt'      # a display-text DAT, not code
        counts[kind] += 1
        write(rel, kind, body)

    for f in glob.glob(os.path.join(SRC, '**', '*.table'), recursive=True):
        try:
            grid = table_grid(f)
        except Exception:
            grid = None
        if grid is None:
            failed.append(f)
            continue
        rel = os.path.relpath(f, SRC).replace(os.sep, '/')[:-6]
        counts['tsv'] += 1
        write(rel, 'tsv', ''.join('\t'.join(r) + '\n' for r in grid))

    print(counts)
    if failed:
        print('UNRESOLVED:')
        for f in failed:
            print('   ', f)
    else:
        print('all DATs extracted')


if __name__ == '__main__':
    main()
