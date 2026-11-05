#!/usr/bin/env python3
"""Build the supplemental Cyrillic atlas from a licensed Ubuntu TTF.

Example: python kit/tools/bake_cyrillic.py /path/to/Ubuntu-Regular.ttf
The generated atlas is committed; Pillow and the TTF are only needed to rebuild it.
"""
import hashlib
import json
import sys
from pathlib import Path

import bake_fonts

font = Path(sys.argv[1]).resolve()
if not font.is_file():
    raise SystemExit('Supply the path to an Ubuntu font TTF')
bake_fonts.FONTDIR = str(font.parent)
characters = bake_fonts.TEXT + ''.join(chr(c) for c in range(0x400, 0x500))
atlas = bake_fonts.bake(font.name, None, 48, characters)
if atlas['atlasH'] > 2048:
    raise SystemExit('Cyrillic atlas exceeds the GPU texture height budget')
cache_key = hashlib.sha256(json.dumps(atlas, separators=(',', ':')).encode()).hexdigest()[:16]
data = {'family': 'cyrillic', 'source': 'Ubuntu (Ubuntu Font Licence 1.0)', 'cacheKey': cache_key, 'sizes': [atlas]}
out = Path(__file__).resolve().parent.parent / 'runtime' / 'fonts' / 'cyrillic.json'
out.write_text(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n', encoding='utf-8')
print('Cyrillic atlas:', atlas['atlasW'], 'x', atlas['atlasH'], 'pixels')
