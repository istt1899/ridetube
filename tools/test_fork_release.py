#!/usr/bin/env python3
"""Check release catalog URLs, integrity and absence of BMW SDK material."""
import hashlib
import json
import tarfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent / 'dist' / 'release'
catalog = json.loads((root / 'catalog.json').read_text(encoding='utf-8'))
assert catalog['schema'] == 2
components = {c['id']: c for c in catalog['components']}
assert set(components) == {'jap_ridetube', 'jap-ridetube-d', 'jap-node22'}
for component in components.values():
    artifact = component['artifact']
    if component['id'] == 'jap-node22':
        assert artifact['url'].startswith('https://github.com/JustAnotherPU/mgu-apps/releases/download/')
        assert artifact['size'] > 0 and len(artifact['sha256']) == 64
        continue
    data = (root / artifact['name']).read_bytes()
    assert len(data) == artifact['size']
    assert hashlib.sha256(data).hexdigest() == artifact['sha256']
    assert artifact['url'].startswith('https://github.com/istt1899/ridetube/releases/download/catalog/')
app = components['jap_ridetube']
assert tuple(map(int, components['jap-node22']['version'].split('.'))) >= tuple(map(int, components['jap-ridetube-d']['requires']['jap-node22'].split('.')))
assert app['version'] == '0.3.8'
with tarfile.open(root / app['artifact']['name']) as archive:
    names = archive.getnames()
    assert not any('oap-sdk' in name for name in names)
    assert 'package/javascript/kit/fonts/cyrillic.json' in names
    assert b'The RideTube service is not connected.' in archive.extractfile('package/javascript/yt.js').read()
    for name in ('package/package.json', 'package/npm-shrinkwrap.json',
                 'package/rhmiData/application.json', 'package/javascript/kit/app-spec.json'):
        doc = json.load(archive.extractfile(name))
        assert (doc.get('version') or doc.get('application', {}).get('version')) == app['version']
print('ok: fork catalog URLs, hashes, app version, code, font and SDK exclusion')
