#!/usr/bin/env python3
"""Repack the RideTube service on Windows without rebuilding its Linux binaries.

The input is the verified upstream 0.3.8 mgu-deploy artifact. Only component.json
and files/ytd.js may change. Every other source file must still match that artifact
(allowing Windows CRLF line endings); the two unavailable Linux build products are
reused byte for byte. The output is a deterministic Store tool artifact.

    python tools/repack_service.py --check
    python tools/repack_service.py
    python tools/repack_service.py --base path/to/jap-ridetube-d@0.3.8.tgz
"""

import argparse
import copy
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile


ROOT = Path(__file__).resolve().parent.parent
COMPONENT = ROOT / 'native' / 'jap-ridetube-d'
DEFAULT_BASE = ROOT.parent / 'RideTube-artifacts' / 'jap-ridetube-d@0.3.8.tgz'
BASE_SHA256 = '627db11ddd499581f84f79f9c3fdd7fb868ac8399bdf0f7c4660d77f4a317147'
REPLACED = frozenset({'component.json', 'files/ytd.js'})
# These are products of the Linux build. They must come from the verified artifact.
REUSED_BINARIES = frozenset({'files/ytdec', 'files/ytdlp.pyz'})


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def normalized(data):
    return data.replace(b'\r\n', b'\n')


def source_path(entry):
    """Resolve a manifest source without accepting paths outside this repository."""
    source = (COMPONENT / entry['from']).resolve()
    if not source.is_relative_to(ROOT.resolve()):
        raise ValueError('source escapes repository: ' + entry['from'])
    return source


def declared_files(component):
    files = {f"files/{entry['path']}": source_path(entry) for entry in component['files']}
    files.update({f"units/{entry['name']}": source_path(entry) for entry in component['units']})
    return files


def validate_component(old, new):
    if old.get('id') != 'jap-ridetube-d' or old.get('version') != '0.3.8':
        raise ValueError('unexpected base component identity or version')
    version = new.get('version', '')
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('new component version must be MAJOR.MINOR.PATCH')
    if tuple(map(int, version.split('.'))) <= (0, 3, 8):
        raise ValueError('new component version must exceed 0.3.8')
    # mgu-deploy turns the source manifest into a smaller install manifest. It
    # adds per-file digests, drops each `from`, and leaves catalog dependencies
    # for tools/release.py. Compare the common fields before doing that here.
    expected = copy.deepcopy(old)
    expected.pop('version')
    for entry in expected['files']:
        entry.pop('sha256')
    actual = copy.deepcopy(new)
    actual.pop('version')
    if actual.pop('license', None) != 'GPL-3.0-or-later' or actual.pop('uninstallable', None) is not True:
        raise ValueError('source license or uninstallable flag changed')
    if actual.pop('requires', None) != {
        'mgu-deploy': '0.7.0', 'mgu-python': '1.0.2',
        'jap-node22': '22.23.4', 'mgu-render': '0.6.11', 'mgu-uplink': '0.7.3',
    }:
        raise ValueError('unexpected source dependencies')
    for entry in actual['files'] + actual['units']:
        if not isinstance(entry.pop('from', None), str):
            raise ValueError('source manifest is missing a file path')
    if actual != expected:
        raise ValueError('source component changed beyond version and mgu-uplink requirement')
    return version


def read_base(base):
    data = base.read_bytes()
    digest = sha256(data)
    if digest != BASE_SHA256:
        raise ValueError(f'unverified base artifact: sha256 {digest}, expected {BASE_SHA256}')
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive.getmembers():
            if not member.isfile() or member.name in members:
                raise ValueError('unexpected or duplicate archive member: ' + member.name)
            members[member.name] = (member, archive.extractfile(member).read())
    return members


def prepare(base):
    members = read_base(base)
    old = json.loads(members['component.json'][1])
    new = json.loads((COMPONENT / 'component.json').read_bytes())
    version = validate_component(old, new)
    source_files = declared_files(new)
    if set(members) != set(source_files) | {'component.json'}:
        raise ValueError('base archive members do not match component manifest')
    if not REUSED_BINARIES <= set(source_files):
        raise ValueError('base archive is missing a required reusable binary')
    for entry in old['files']:
        name = 'files/' + entry['path']
        if sha256(members[name][1]) != entry['sha256']:
            raise ValueError('base archive file hash differs from its manifest: ' + name)
    new_ytd = normalized(source_files['files/ytd.js'].read_bytes())
    packed_component = copy.deepcopy(old)
    packed_component['version'] = version
    next(entry for entry in packed_component['files'] if entry['path'] == 'ytd.js')['sha256'] = sha256(new_ytd)
    replacements = {
        'component.json': (json.dumps(packed_component, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
        'files/ytd.js': new_ytd,
    }
    for name, source in source_files.items():
        if name in REPLACED:
            continue
        if not source.is_file():
            if name in REUSED_BINARIES:
                continue
            raise ValueError('unchanged source is missing: ' + str(source))
        current = source.read_bytes()
        archived = members[name][1]
        # Binary comparisons are exact. Text source may have CRLF after checkout on Windows.
        equal = current == archived if name in REUSED_BINARIES else normalized(current) == normalized(archived)
        if not equal:
            raise ValueError('unchanged source differs from verified artifact: ' + name)
    return version, members, replacements


def pack(members, replacements, epoch):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(members):
            old_member, old_data = members[name]
            data = replacements.get(name, old_data)
            member = copy.copy(old_member)
            member.size = len(data)
            member.mtime = epoch
            archive.addfile(member, io.BytesIO(data))
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=epoch, compresslevel=9) as zipped:
        zipped.write(buffer.getvalue())
    return output.getvalue()


def verify_output(data, original, replacements):
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        names = archive.getnames()
        if names != sorted(original):
            raise ValueError('output member list changed unexpectedly')
        for name in names:
            actual = archive.extractfile(name).read()
            expected = replacements.get(name, original[name][1])
            if actual != expected:
                raise ValueError('output member differs: ' + name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, default=DEFAULT_BASE, help='verified upstream 0.3.8 service artifact')
    parser.add_argument('--check', action='store_true', help='validate inputs without writing an artifact')
    args = parser.parse_args()
    version, members, replacements = prepare(args.base)
    target = COMPONENT / 'dist' / f'jap-ridetube-d@{version}.tgz'
    if args.check:
        print(f'OK: verified base and unchanged sources; ready to build {target}')
        return
    epoch = int(os.environ.get('SOURCE_DATE_EPOCH', '0'))
    if epoch < 0:
        raise ValueError('SOURCE_DATE_EPOCH must be nonnegative')
    data = pack(members, replacements, epoch)
    verify_output(data, members, replacements)
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, prefix='.repack-', suffix='.tmp', delete=False) as temp:
        temp.write(data)
        temporary = Path(temp.name)
    try:
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f'{target}: {len(data)} bytes; sha256 {sha256(data)}')
    for name in sorted(replacements):
        print(f'  {name}: sha256 {sha256(replacements[name])}')
    for name in sorted(REUSED_BINARIES):
        print(f'  reused {name}: sha256 {sha256(members[name][1])}')


if __name__ == '__main__':
    main()
