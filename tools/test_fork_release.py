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
assert app['version'] == '0.3.13'
service = components['jap-ridetube-d']
assert service['version'] == '0.3.13'
assert app['requires']['jap-ridetube-d'] == service['version']
assert service['requires']['mgu-uplink'] == '0.7.3'
direct = json.loads((root.parent.parent / 'catalog.json').read_text(encoding='utf-8'))
direct_components = {c['id']: c for c in direct['components']}
assert set(direct_components) == set(components)
for name, component in components.items():
    assert direct_components[name]['version'] == component['version']
    assert direct_components[name]['artifact'] == component['artifact']
assert direct_components['jap_ridetube']['icon'] == components['jap_ridetube']['artifact']['url'].rsplit('/', 1)[0] + '/jap_ridetube.png'
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
    assert any(f['path'] == 'proxy.js' for f in manifest['files'])
    for entry in manifest['files']:
        data = archive.extractfile('files/' + entry['path']).read()
        assert hashlib.sha256(data).hexdigest() == entry['sha256']
print('ok: fork catalog URLs, hashes, versions, uplink dependency, code, font and SDK exclusion')
