#!/usr/bin/env python3
"""Bump the app artifact's version without a kit rebuild (the app's code is unchanged).

Reads the verified jap_ridetube@0.3.10 release artifact, replaces the version in every
file that carries it (package.json, npm-shrinkwrap.json, rhmiData/application.json,
javascript/kit/app-spec.json), and repacks deterministically (sorted members, uid/gid 0,
one mtime). Refuses any other 0.3.10 occurrence or content change.

    python tools/patch_app_version.py            # writes dist/release/jap_ridetube@0.3.11.tgz
    python tools/patch_app_version.py --check    # list what would change
"""
import argparse
import copy
import gzip
import hashlib
import io
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT.parent / 'RideTube-artifacts' / 'jap_ridetube@0.3.11.tgz'
BASE_SHA256 = '61685ce047aefb88b61a86146ef580a2b2a6669285584a38b084b1ce2fee6a88'
OLD, NEW = '0.3.11', '0.3.12'
VERSION_FILES = {
    'package/package.json',
    'package/npm-shrinkwrap.json',
    'package/rhmiData/application.json',
    'package/javascript/kit/app-spec.json',
}


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    data = BASE.read_bytes()
    if sha256(data) != BASE_SHA256:
        raise SystemExit('unverified app artifact: sha256 ' + sha256(data))
    members = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive.getmembers():
            if member.name in members:
                raise SystemExit('unexpected duplicate member: ' + member.name)
            members[member.name] = (member, archive.extractfile(member).read() if member.isfile() else None)
    changed = {}
    for name, (member, blob) in members.items():
        if blob is None:
            continue
        if OLD.encode() in blob:
            if name not in VERSION_FILES:
                raise SystemExit('0.3.10 outside the known version files: ' + name)
            j = json.loads(blob)
            holder = j['application'] if name == 'package/rhmiData/application.json' else j
            if holder.get('version') != OLD:
                raise SystemExit(name + ': version field is not ' + OLD)
            holder['version'] = NEW
            changed[name] = (json.dumps(j, indent=1 if name.endswith('app-spec.json') else 2, ensure_ascii=False) + '\n').encode('utf-8')
            # the artifact's own layout kept these at indent 1/2; re-indent freely, content is what matters
            print(f'{name}: version {OLD} -> {NEW}')
    if set(changed) != VERSION_FILES:
        raise SystemExit('missing version files: ' + ', '.join(sorted(VERSION_FILES - set(changed))))
    if args.check:
        print('OK: four version files, nothing else')
        return
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as out:
        for name in sorted(members):
            member, blob = members[name]
            blob = changed.get(name, blob)
            m = copy.copy(member)
            m.mtime = 0
            if blob is not None:
                m.size = len(blob)
                out.addfile(m, io.BytesIO(blob))
            else:
                out.addfile(m)
    output = io.BytesIO()
    with gzip.GzipFile(fileobj=output, mode='wb', filename='', mtime=0, compresslevel=9) as zipped:
        zipped.write(buffer.getvalue())
    target = ROOT / 'dist' / f'jap_ridetube@{NEW}.tgz'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(output.getvalue())
    print(f'{target}: {len(output.getvalue())} bytes; sha256 {sha256(output.getvalue())}')


if __name__ == '__main__':
    main()
