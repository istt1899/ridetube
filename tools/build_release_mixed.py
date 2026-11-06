#!/usr/bin/env python3
"""Assemble dist/release/ for the 0.3.11 service update without rebuilding the unchanged app.

The app (jap_ridetube 0.3.10) and the pinned jap-node22 provider are reused byte for byte from
the published catalog release; only jap-ridetube-d becomes 0.3.11. Mirrors tools/release.py's
output for this mixed update (release.py itself would require the oap-sdk to rebuild the app).
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://github.com/istt1899/ridetube/releases/download/catalog/'
OUT = ROOT / 'dist' / 'release'
OUT.mkdir(parents=True, exist_ok=True)

APP_ART = {'name': 'jap_ridetube@0.3.10.tgz', 'size': 1287022,
           'sha256': 'c72d74b9aa1cbc60711181faab8ad81b6052c5c95e0ae3b74b370ebe04a78a8a'}
ICON_SHA = 'afbf63c28de964d4f249f062bdbddf853fe1e676cc8d62f59028ea0f1c6a9876'


def sha256(p):
    h = hashlib.sha256()
    with open(p, 'rb') as f:
        for b in iter(lambda: f.read(1 << 20), b''):
            h.update(b)
    return h.hexdigest()


app_pkg = OUT / APP_ART['name']
if not app_pkg.is_file():
    urllib.request.urlretrieve(BASE + APP_ART['name'], app_pkg)
assert os.path.getsize(app_pkg) == APP_ART['size'], 'app package size changed'
assert sha256(app_pkg) == APP_ART['sha256'], 'app package hash changed'

service = json.load(open(ROOT / 'native' / 'jap-ridetube-d' / 'component.json'))
svc_pkg = ROOT / 'native' / 'jap-ridetube-d' / 'dist' / f"jap-ridetube-d@{service['version']}.tgz"
assert svc_pkg.is_file(), 'repack the service first'
shutil.copy(svc_pkg, OUT / svc_pkg.name)

icon = OUT / 'jap_ridetube.png'
shutil.copy(ROOT / 'apps' / 'jap_ridetube' / 'icon.png', icon)
assert sha256(icon) == ICON_SHA and icon.stat().st_size <= 128 * 1024

providers = json.load(open(ROOT / 'tools' / 'runtime-providers.json'))

comps = [
    {'id': 'jap_ridetube', 'kind': 'app', 'title': 'RideTube',
     'description': 'Video in the car: an unofficial client for YouTube. Your Home, Subscriptions and Watch later (signed in on the car), search, channels and chapters; the sound through the car\'s media player, the picture only while parked (a podcast view while driving). Needs the jap-ridetube-d tool.',
     'version': '0.3.10',
     'artifact': {'name': APP_ART['name'], 'size': os.path.getsize(app_pkg), 'sha256': sha256(app_pkg),
                  'url': BASE + APP_ART['name']},
     'requires': {'jap-ridetube-d': service['version'], 'mgu-render': '0.6.11', 'mgu-inputgate': '1.0.0'},
     'uninstallable': True, 'mguHmi': ['ID7'],
     'icon': BASE + 'jap_ridetube.png', 'iconSha256': sha256(icon)},
    {'id': 'jap-ridetube-d', 'kind': 'tool', 'title': service['title'], 'description': service['description'],
     'version': service['version'],
     'artifact': {'name': svc_pkg.name, 'size': os.path.getsize(OUT / svc_pkg.name),
                  'sha256': sha256(OUT / svc_pkg.name), 'url': BASE + svc_pkg.name},
     'requires': service['requires'], 'uninstallable': True, 'mguHmi': ['ID7']},
]
for p in providers:
    assert p['id'] == 'jap-node22'
    comps.append(p)

(OUT / 'catalog.json').write_text(json.dumps({'schema': 2, 'components': comps}, indent=2) + '\n')
shutil.copy(OUT / 'catalog.json', ROOT / 'catalog.json')

for n in sorted(os.listdir(OUT)):
    print(f'{os.path.getsize(OUT / n):>10}  {n}')
print('service', service['version'], sha256(OUT / svc_pkg.name))
