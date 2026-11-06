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
assert set(components) == {'jap_ridetube', 'jap-ridetube-d'}
for component in components.values():
    artifact = component['artifact']
    data = (root / artifact['name']).read_bytes()
    assert len(data) == artifact['size']
    assert hashlib.sha256(data).hexdigest() == artifact['sha256']
    assert artifact['url'].startswith('https://github.com/istt1899/ridetube/releases/download/catalog/')
app = components['jap_ridetube']
assert app['version'] == '0.3.9'
service = components['jap-ridetube-d']
assert service['version'] == '0.3.9'
assert app['requires']['jap-ridetube-d'] == service['version']
assert service['requires']['mgu-uplink'] == '0.7.3'
with tarfile.open(root / app['artifact']['name']) as archive:
    names = archive.getnames()
    assert not any('oap-sdk' in name for name in names)
    assert 'package/javascript/kit/fonts/cyrillic.json' in names
    assert b'The RideTube service is not connected.' in archive.extractfile('package/javascript/yt.js').read()
    for name in ('package/package.json', 'package/npm-shrinkwrap.json',
                 'package/rhmiData/application.json', 'package/javascript/kit/app-spec.json'):
        doc = json.load(archive.extractfile(name))
        assert (doc.get('version') or doc.get('application', {}).get('version')) == app['version']
with tarfile.open(root / service['artifact']['name']) as archive:
    manifest = json.load(archive.extractfile('component.json'))
    assert manifest['version'] == service['version']
    for entry in manifest['files']:
        data = archive.extractfile('files/' + entry['path']).read()
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
print('ok: fork catalog URLs, hashes, versions, uplink dependency, code, font and SDK exclusion')
