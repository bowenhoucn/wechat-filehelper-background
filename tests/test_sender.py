"""Offline behavior tests; these never import the real native adapter."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/wechat-filehelper-background/scripts'
sys.path.insert(0, str(SCRIPTS))
from common import exclusive_lock, hidden_run, save_json, sha256, verify_files
from send_file import Ledger, accepted, import_receipt, protect_snapshot, send


class FakeAdapter:
    def __init__(self, home, account='a' * 64, mode='ok'):
        self.identity = {'account_sha256': account, 'pid': 1, 'wechat_version': 'test'}
        self.mode = mode
        self.calls = []

    def check(self):
        pass

    def dispatch(self, path, *, probe):
        self.calls.append(probe)
        if not probe and self.mode == 'timeout':
            raise TimeoutError('simulated callback timeout')
        if not probe and self.mode == 'crash':
            os._exit(71)
        report = {'completion_success': True, 'target': 'filehelper', 'file_path': str(path),
                  'operation': 'file_probe' if probe else 'file_send', 'message_type': 49,
                  'app_type': 6, 'sent': not probe, 'bytes': path.stat().st_size,
                  'native_status': 0, 'native_status_high': 0}
        result = {'success': True, 'code': 0, 'cleanup_code': 0, 'dll_unloaded': True, 'report': report}
        if probe and self.mode == 'probe_fail':
            result['success'] = False
        if not probe and self.mode == 'unload_fail':
            result['dll_unloaded'] = False
        if not probe and self.mode == 'wrong_recipient':
            report['target'] = 'someone_else'
        return result


class SenderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='wxskill-')
        self.base = Path(self.temp.name)
        self.home = self.base / 'shared'
        self.file = self.base / '结果 文档.pdf'
        self.file.write_bytes(b'%PDF synthetic test only\n')
        self.adapter = FakeAdapter(self.home)

    def tearDown(self):
        self.temp.cleanup()

    def perform(self, path=None, **kwargs):
        return send(path or self.file, self.home, lambda home: self.adapter, **kwargs)

    def test_receipt_and_snapshot_have_exact_content(self):
        result = self.perform()
        self.assertEqual(result['status'], 'native_submission_accepted')
        self.assertFalse(result['server_upload_completion_independently_verified'])
        self.assertEqual(sha256(result['snapshot_path']), sha256(self.file))
        self.assertEqual(json.loads(Path(result['receipt_path']).read_text(encoding='utf-8')), result)
        self.assertEqual(self.adapter.calls, [True, False])

    def test_rename_and_new_instance_do_not_resend(self):
        old = self.perform()
        renamed = self.base / 'renamed.bin'
        renamed.write_bytes(self.file.read_bytes())
        self.adapter = FakeAdapter(self.home)
        result = self.perform(renamed)
        self.assertEqual(result['status'], 'duplicate_blocked')
        self.assertEqual(result['receipt_path'], old['receipt_path'])
        self.assertEqual(self.adapter.calls, [])

    def test_modified_content_is_a_new_send(self):
        first = self.perform()
        self.file.write_bytes(b'new content')
        second = self.perform()
        self.assertNotEqual(first['sha256'], second['sha256'])
        self.assertEqual(second['status'], 'native_submission_accepted')

    def test_account_scope(self):
        self.perform()
        self.adapter = FakeAdapter(self.home, account='b' * 64)
        self.assertEqual(self.perform()['status'], 'native_submission_accepted')

    def test_explicit_resend_preserves_old_receipt(self):
        old = self.perform()
        old_bytes = Path(old['receipt_path']).read_bytes()
        new = self.perform(resend_reason='User explicitly requested another copy')
        self.assertEqual(new['previous_attempt_id'], old['id'])
        self.assertNotEqual(new['id'], old['id'])
        self.assertEqual(Path(old['receipt_path']).read_bytes(), old_bytes)

    def test_unknown_callback_never_retries(self):
        self.adapter.mode = 'timeout'
        result = self.perform()
        self.assertEqual(result['status'], 'needs_reconciliation')
        self.adapter = FakeAdapter(self.home)
        self.assertEqual(self.perform()['status'], 'duplicate_blocked')
        self.assertEqual(self.adapter.calls, [])

    def test_probe_failure_can_be_fixed_without_false_send(self):
        self.adapter.mode = 'probe_fail'
        result = self.perform()
        self.assertEqual(result['status'], 'failed_before_dispatch')
        self.assertEqual(self.adapter.calls, [True])
        self.adapter = FakeAdapter(self.home)
        self.assertEqual(self.perform()['status'], 'native_submission_accepted')
        self.assertTrue(Path(result['receipt_path']).exists())

    def test_unload_failure_stays_uncertain_and_blocking(self):
        self.adapter.mode = 'unload_fail'
        self.assertEqual(self.perform()['status'], 'needs_reconciliation')
        self.assertEqual(self.perform()['status'], 'duplicate_blocked')

    def test_wrong_recipient_is_never_accepted(self):
        self.adapter.mode = 'wrong_recipient'
        self.assertEqual(self.perform()['status'], 'needs_reconciliation')

    def test_empty_or_missing_file_never_dispatches(self):
        empty = self.base / 'empty'
        empty.touch()
        for file in (empty, self.base / 'missing'):
            with self.assertRaises((ValueError, FileNotFoundError)):
                self.perform(file)
        self.assertEqual(self.adapter.calls, [])

    def test_integrity_check_rejects_changed_runtime(self):
        expected = sha256(self.file)
        verify_files(self.base, {self.file.name: expected})
        self.file.write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError, 'integrity mismatch'):
            verify_files(self.base, {self.file.name: expected})

    @unittest.skipUnless(os.name == 'nt', 'Windows file sharing test')
    def test_snapshot_cannot_be_modified_while_native_reads(self):
        with protect_snapshot(self.file):
            with self.assertRaises(PermissionError):
                self.file.write_bytes(b'overwrite')
        self.assertTrue(self.file.read_bytes().startswith(b'%PDF'))

    def test_cross_process_lock_and_release(self):
        code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'from common import exclusive_lock; '\
                '\nwith exclusive_lock(Path(sys.argv[2])): print("acquired")')
        with exclusive_lock(self.home):
            result = hidden_run([sys.executable, '-c', code, SCRIPTS, self.home], check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Another filehelper operation', result.stderr)
        result = hidden_run([sys.executable, '-c', code, SCRIPTS, self.home])
        self.assertIn('acquired', result.stdout)

    def test_hard_process_crash_leaves_reservation(self):
        # os._exit bypasses all exception handlers and finally blocks.
        code = ('import sys; from pathlib import Path; sys.path.insert(0,sys.argv[1]); '
                'from test_sender import FakeAdapter, send; '
                'send(Path(sys.argv[2]),Path(sys.argv[3]),lambda h:FakeAdapter(h,mode="crash"))')
        result = hidden_run([sys.executable, '-c', code, Path(__file__).parent, self.file, self.home], check=False)
        self.assertEqual(result.returncode, 71, result.stderr)
        result = self.perform()
        self.assertEqual(result['status'], 'duplicate_blocked')
        self.assertEqual(result['previous_status'], 'dispatch_started')
        self.assertEqual(self.adapter.calls, [])

    def test_legacy_import_prevents_duplicate(self):
        receipt = self.base / 'legacy-receipt.json'
        attempt = self.base / 'legacy-attempt.json'
        shared = {'status': 'native_submission_accepted', 'sha256': sha256(self.file),
                  'bytes': self.file.stat().st_size}
        save_json(receipt, {**shared, 'recipient_id': 'filehelper'})
        save_json(attempt, {**shared, 'recipient': 'filehelper', 'account_sha256': 'a' * 64})
        imported = import_receipt(receipt, attempt, self.home)
        self.assertEqual(imported['status'], 'historical_submission_imported')
        self.assertEqual(self.perform()['status'], 'duplicate_blocked')
        self.assertEqual(self.adapter.calls, [])

    def test_mismatched_legacy_records_are_rejected(self):
        receipt = self.base / 'legacy.json'
        save_json(receipt, {'status': 'native_submission_accepted', 'recipient_id': 'friend'})
        with self.assertRaises(ValueError):
            import_receipt(receipt, receipt, self.home)


if __name__ == '__main__':
    unittest.main()
