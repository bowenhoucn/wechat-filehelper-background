"""Real offline install/repair tests plus archive integrity checks; no WeChat use."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/wechat-filehelper-background/scripts'
sys.path.insert(0, str(SCRIPTS))
from bootstrap import extract_bundle, install
from common import LOCK, SKILL, sha256, runtime_paths, verify_runtime


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='wxbootstrap-')
        self.home = Path(self.tmp.name) / 'state'

    def tearDown(self):
        self.tmp.cleanup()

    def test_install_without_git_or_network_and_repair_preserves_history(self):
        # --no-index + a deliberately invalid proxy confirms pip uses the bundled wheel.
        import os
        with patch('bootstrap.require_windows'), patch.dict(os.environ, {
            'HTTPS_PROXY': 'http://127.0.0.1:1', 'HTTP_PROXY': 'http://127.0.0.1:1',
            'PIP_INDEX_URL': 'http://127.0.0.1:1', 'PIP_NO_INDEX': '1'}):
            result = install(self.home)
            self.assertFalse(result['reused'])
            repo, deps = verify_runtime(self.home)
            self.assertTrue((repo / 'native/file_send.h').exists())
            self.assertTrue((repo / 'LICENSE').exists())
            self.assertTrue((deps / 'pefile.py').exists())
            self.assertTrue(install(self.home)['reused'])
            history = self.home / 'receipts/keep.json'
            history.parent.mkdir()
            history.write_bytes(b'{"keep":true}')
            (repo / 'native/run_selftest.py').unlink()
            repaired = install(self.home)
            self.assertTrue(Path(repaired['preserved_previous_runtime']).exists())
            verify_runtime(self.home)
            self.assertEqual(history.read_bytes(), b'{"keep":true}')

    def test_modified_bundle_is_rejected_before_extracting(self):
        archive = Path(self.tmp.name) / 'bad.zip'
        archive.write_bytes(b'wrong')
        with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
            extract_bundle(archive, self.home, LOCK['bundle']['sha256'])
        self.assertFalse(self.home.exists())

    def test_path_traversal_bundle_is_rejected(self):
        archive = Path(self.tmp.name) / 'evil.zip'
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('../escape.txt', 'bad')
        with self.assertRaisesRegex(RuntimeError, 'Invalid bundled archive path'):
            extract_bundle(archive, self.home, sha256(archive))
        self.assertFalse((Path(self.tmp.name) / 'escape.txt').exists())

    def test_missing_bundle_is_diagnostic(self):
        with self.assertRaisesRegex(RuntimeError, 'including assets'):
            extract_bundle(Path(self.tmp.name) / 'absent.zip', self.home, '0' * 64)


if __name__ == '__main__':
    unittest.main()
