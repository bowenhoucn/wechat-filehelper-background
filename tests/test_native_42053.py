import hashlib
import importlib
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/wechat-filehelper-background/scripts'))
import native_42053 as native


class BridgeIntegrity(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'references').mkdir()
        (self.root/'assets').mkdir()
        (self.root/'native').mkdir()
        (self.root/'assets/file.dll').write_bytes(b'bridge fixture')
        (self.root/'native/file.cpp').write_bytes(b'source fixture')
        self.lock={'core':native.CORE,'binary':'assets/file.dll',
                   'binary_sha256':hashlib.sha256(b'bridge fixture').hexdigest(),
                   'sources':{'native/file.cpp':hashlib.sha256(b'source fixture').hexdigest()}}
        self.write_lock()
        self.patcher=patch.object(native,'SKILL',self.root);self.patcher.start()

    def tearDown(self):self.patcher.stop();self.temp.cleanup()

    def write_lock(self):
        (self.root/'references/native-4.2.0.53.json').write_text(json.dumps(self.lock),encoding='utf-8')

    def test_intact_bundle_and_modified_binary(self):
        self.assertEqual(native.checked_bridge()[0],self.root/'assets/file.dll')
        (self.root/'assets/file.dll').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'integrity'):native.checked_bridge()

    def test_source_drift_is_rejected(self):
        (self.root/'native/file.cpp').write_bytes(b'changed')
        with self.assertRaisesRegex(RuntimeError,'source integrity'):native.checked_bridge()

    def test_outside_binary_rejected_even_with_matching_hash(self):
        self.lock['binary']='../file.dll';self.write_lock()
        outside=self.root.parent/'file.dll'
        outside.write_bytes(b'bridge fixture')
        try:
            with self.assertRaisesRegex(RuntimeError,'integrity'):native.checked_bridge()
        finally:outside.unlink()

    def test_inexact_core_rejected(self):
        self.lock['core']={**native.CORE,'sha256':'0'*64};self.write_lock()
        with self.assertRaisesRegex(RuntimeError,'core manifest'):native.checked_bridge()

    def test_missing_manifest_has_installation_diagnosis(self):
        (self.root/'references/native-4.2.0.53.json').unlink()
        with self.assertRaisesRegex(RuntimeError,'Incomplete skill package'):native.checked_bridge()

    def test_missing_dll_has_installation_diagnosis(self):
        (self.root/'assets/file.dll').unlink()
        with self.assertRaisesRegex(RuntimeError,'native attachment DLL is missing'):native.checked_bridge()


class AccountGuard(unittest.TestCase):
    def test_unknown_core_never_opens_account_memory(self):
        fake=types.ModuleType('run_selftest')
        fake.modules=lambda pid:{'weixin.dll':(4096,__file__)}
        fake.K=types.SimpleNamespace(OpenProcess=lambda *a: self.fail('Account memory opened for wrong core'))
        fake.check=lambda *a:None
        account=types.ModuleType('wxbot_framework.account');account.read_current_account=lambda *a,**k:None
        profiles=types.ModuleType('wxbot_framework.native_profiles');profiles.CoreProfile=lambda *a:None
        with patch.dict(sys.modules,{'run_selftest':fake,'wxbot_framework.account':account,'wxbot_framework.native_profiles':profiles}):
            with self.assertRaisesRegex(RuntimeError,'Unexpected WeChat core'):native.inspect_account(1)

if __name__=='__main__':unittest.main()
