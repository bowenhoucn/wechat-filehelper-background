import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, Mock
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'skills/wechat-filehelper-background/scripts'))
import compatibility as compat
from native_adapter import NativeAdapter

class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        (self.root/'references').mkdir()
        self.core=self.root/'Weixin.dll'
        self.core.write_bytes(b'fake-core')
        self.profile={'version':'4.2.0.53','size':9,'sha256':'candidate'}
        self.doc={'profile':self.profile,'unmapped_attachment_interfaces':['ordinary_file_message_factory'],
                  'source':{'commit':'test-only'}}
        (self.root/'references/candidate-4.2.0.53.json').write_text(json.dumps(self.doc))
    def tearDown(self): self.temp.cleanup()
    def classify(self, digest, registered=None):
        with patch.object(compat,'SKILL',self.root), patch.object(compat,'LOCK',{'validated_cores':registered or []}), \
             patch.object(compat,'file_version',return_value='4.2.0.53'):
            return compat.classify_core(self.core,digest)
    def test_candidate_does_not_enable_attachments(self):
        r=self.classify('candidate')
        self.assertTrue(r['candidate_mapping_found'])
        self.assertFalse(r['attachment_adapter_validated'])
    def test_wrong_fingerprint_not_candidate(self):
        self.assertFalse(self.classify('other')['candidate_mapping_found'])
    def test_missing_candidate_file_does_not_hide_core_version(self):
        (self.root/'references/candidate-4.2.0.53.json').unlink()
        r=self.classify('candidate')
        self.assertEqual(r['wechat_version'],'4.2.0.53')
        self.assertTrue(r['candidate_metadata_missing'])
        self.assertFalse(r['attachment_adapter_validated'])
    def test_static_mapping_complete_is_still_not_enabled(self):
        self.doc.update(status='static_mapping_complete_not_native_validated',
                        unmapped_attachment_interfaces=[],
                        static_attachment_candidates={'factory': {'rva':'0x123'}},
                        pending_validation=['native probe'])
        (self.root/'references/candidate-4.2.0.53.json').write_text(json.dumps(self.doc))
        r=self.classify('candidate')
        self.assertFalse(r['attachment_adapter_validated'])
        self.assertEqual(r['pending_validation'],['native probe'])
    def test_existing_exact_profile_preserved(self):
        r=self.classify('old',[{'size':9,'sha256':'old','wechat_version':'4.1.15.56'}])
        self.assertTrue(r['attachment_adapter_validated'])
        self.assertEqual(r['wechat_version'],'4.1.15.56')
    def test_unsupported_core_does_not_read_account_or_dispatch(self):
        inspect=Mock()
        dispatch=Mock()
        helpers=SimpleNamespace(TEXT_DLL=self.root/'bridge.dll',modules=lambda _: {'weixin.dll':(0,str(self.core))},
                                run=dispatch,wechat_candidates=lambda:[123])
        with patch('native_adapter.require_windows'),patch('native_adapter.verify_runtime',return_value=(self.root,self.root)), \
             patch('native_adapter.LOCK',{'validated_cores':[]}),patch('native_adapter.sha256',return_value='candidate'), \
             patch('native_adapter.classify_core',return_value={'wechat_version':'4.2.0.53'}), \
             patch.dict(sys.modules,{'run_selftest':helpers,'text_service':SimpleNamespace(inspect_account=inspect)}):
            with self.assertRaises(compat.CompatibilityError) as ctx: NativeAdapter(self.root)
        inspect.assert_not_called()
        dispatch.assert_not_called()
        self.assertFalse(ctx.exception.details['native_send_called'])

    def test_validated_new_core_routes_to_file_adapter_without_old_dispatch(self):
        old_inspect,old_dispatch=Mock(),Mock()
        new=Mock()
        new.identity={'account_sha256':'a'*64,'wechat_version':'4.2.0.53'}
        profile={'size':9,'sha256':'validated','wechat_version':'4.2.0.53','adapter':'native_42053'}
        helpers=SimpleNamespace(TEXT_DLL=self.root/'old.dll',modules=lambda _: {'weixin.dll':(0,str(self.core))},
                                run=old_dispatch,wechat_candidates=lambda:[123])
        with patch('native_adapter.require_windows'),patch('native_adapter.verify_runtime',return_value=(self.root,self.root)), \
             patch('native_adapter.LOCK',{'validated_cores':[profile],'commit':'locked'}), \
             patch('native_adapter.sha256',return_value='validated'), \
             patch('native_42053.inspect_account',return_value='current-account'), \
             patch('native_42053.Adapter42053',return_value=new) as factory, \
             patch.dict(sys.modules,{'run_selftest':helpers,'text_service':SimpleNamespace(inspect_account=old_inspect)}):
            adapter=NativeAdapter(self.root)
            adapter.check()
            adapter.dispatch(self.core,probe=True)
        factory.assert_called_once_with(self.root,123)
        new.check.assert_called_once_with()
        new.dispatch.assert_called_once_with(self.core,probe=True)
        old_inspect.assert_not_called()
        old_dispatch.assert_not_called()

if __name__=='__main__': unittest.main()
