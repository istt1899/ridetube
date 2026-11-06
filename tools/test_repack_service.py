#!/usr/bin/env python3
"""Checks for the Windows service repack path; no release file is written."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest import mock

import repack_service as repack


class RepackServiceTest(unittest.TestCase):
    def test_repack_preserves_every_other_file_and_updates_manifest_hash(self):
        version, members, replacements = repack.prepare(repack.DEFAULT_BASE)
        self.assertNotEqual(version, '0.3.8')
        built = repack.pack(members, replacements, 0)
        self.assertEqual(built, repack.pack(members, replacements, 0))
        repack.verify_output(built, members, replacements)
        with tarfile.open(fileobj=io.BytesIO(built), mode='r:gz') as archive:
            packed = json.load(archive.extractfile('component.json'))
            self.assertEqual(packed['version'], version)
            ytd = archive.extractfile('files/ytd.js').read()
            self.assertEqual(
                next(file['sha256'] for file in packed['files'] if file['path'] == 'ytd.js'),
                repack.sha256(ytd),
            )
            for name in set(members) - repack.REPLACED:
                self.assertEqual(archive.extractfile(name).read(), members[name][1], name)

    def test_rejects_unexpected_source_change(self):
        source = repack.declared_files(json.loads((repack.COMPONENT / 'component.json').read_bytes()))
        with tempfile.TemporaryDirectory() as temp:
            changed = Path(temp) / 'thumb.js'
            changed.write_bytes(b'unexpected edit\n')
            source['files/thumb.js'] = changed
            with mock.patch.object(repack, 'declared_files', return_value=source):
                with self.assertRaisesRegex(ValueError, 'unchanged source differs'):
                    repack.prepare(repack.DEFAULT_BASE)

    def test_rejects_unverified_base(self):
        with mock.patch.object(repack, 'BASE_SHA256', '0' * 64):
            with self.assertRaisesRegex(ValueError, 'unverified base artifact'):
                repack.prepare(repack.DEFAULT_BASE)


if __name__ == '__main__':
    unittest.main()
