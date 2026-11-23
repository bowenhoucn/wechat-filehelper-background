"""Exact-core, file-only desktop bridge. No UI, chat database, or credentials."""
from __future__ import annotations
import ctypes as c
import hashlib
import json
import struct
from pathlib import Path
import time
from types import MappingProxyType
import uuid

from common import SKILL, sha256, save_json

CORE = {
    'wechat_version': '4.2.0.53',
    'size': 204154920,
    'sha256': 'ac6b174d98ee1b69e95c99a7a39c3197c8c167b7c6d32f5b72c7a7659c104825',
    'adapter': 'native_42053',
}
IDENTITY_RVAS = {0xB912690:0xBB6B788, 0x8D804E8:0x901B0E8,
                 0x8DFE2F8:0x90CCCB8, 0x469A0:0x20920, 0x36F930:0x358810}


def inspect_account(pid):
    from run_selftest import modules, K, check
    from wxbot_framework.account import read_current_account
    from wxbot_framework.native_profiles import CoreProfile
    core=modules(pid).get('weixin.dll')
    if not core or Path(core[1]).stat().st_size!=CORE['size'] or sha256(core[1])!=CORE['sha256']:
        raise RuntimeError('Unexpected WeChat core before account read')
    profile=CoreProfile(CORE['wechat_version'],CORE['size'],CORE['sha256'],MappingProxyType(IDENTITY_RVAS),b'')
    h=check(K.OpenProcess(0x410,False,pid),'Read current account')
    try:
        def read(addr,length):
            buf=c.create_string_buffer(length); count=c.c_size_t()
            check(K.ReadProcessMemory(h,addr,buf,length,c.byref(count)),'Read account identity')
            if count.value!=length:raise RuntimeError('Short account read')
            return buf.raw
        return read_current_account(read,core[0],profiles=(profile,))
    finally:K.CloseHandle(h)


def checked_bridge():
    metadata=SKILL/'references/native-4.2.0.53.json'
    if not metadata.is_file():
        raise RuntimeError('Incomplete skill package: reinstall the complete skill including references/native-4.2.0.53.json; keep the shared ledger')
    lock=json.loads(metadata.read_text(encoding='utf-8'))
    if lock['core']!=CORE:raise RuntimeError('Bridge core manifest mismatch')
    path=(SKILL/lock['binary']).resolve()
    if not path.is_file():
        raise RuntimeError('Incomplete skill package: native attachment DLL is missing; reinstall the complete skill and keep the shared ledger')
    if not path.is_relative_to(SKILL.resolve()) or sha256(path)!=lock['binary_sha256']:
        raise RuntimeError('New native bridge integrity mismatch')
    for name,digest in lock['sources'].items():
        target=(SKILL/name).resolve()
        if not target.is_file() or not target.is_relative_to(SKILL.resolve()) or sha256(target)!=digest:
            raise RuntimeError('New native bridge source integrity mismatch')
    return path,lock


class Adapter42053:
    def __init__(self,home,pid):
        self.home,self.pid=Path(home),pid
        self.dll,self.manifest=checked_bridge()
        self.account=inspect_account(pid)
        if not self.account:raise RuntimeError('Exact-core account is not ready')
        self.identity={'account_sha256':hashlib.sha256(self.account.encode()).hexdigest(),
                       'pid':pid,'wechat_version':CORE['wechat_version'],'core_sha256':CORE['sha256'],
                       'bridge_sha256':self.manifest['binary_sha256'],'adapter':'native_42053'}
        self.check()

    def check(self):
        from run_selftest import modules
        if any(name.endswith('bridge.dll') for name in modules(self.pid)):
            raise RuntimeError('A native bridge is already active; do not unload or replace it')
        if inspect_account(self.pid)!=self.account:
            raise RuntimeError('Current account changed')
        checked_bridge()

    def dispatch(self,path,*,probe):
        import pefile
        from run_selftest import K,check,modules,remote_call,remote_system_function,FileConfig
        self.check()
        path=Path(path).resolve(strict=True)
        encoded=str(path).encode('utf-8')
        if len(encoded)>1023 or b'\0' in encoded or not path.is_file():
            raise ValueError('Invalid local attachment path')
        report_path=self.home/'receipts'/('native42053_'+uuid.uuid4().hex+'.json')
        report_path.parent.mkdir(parents=True,exist_ok=True)
        if len(str(report_path))>=260:raise ValueError('Native receipt path too long')
        pe=pefile.PE(str(self.dll))
        exports={item.name:item.address for item in pe.DIRECTORY_ENTRY_EXPORT.symbols}
        pe.close()
        name=b'WxInspectFilePath' if probe else b'WxSendFile'
        if not {name,b'WxRemoveSelfTest',b'WxFileDiagnostics',b'WxFileReport'} <= exports.keys():
            raise RuntimeError('Missing native file exports')
        process=check(K.OpenProcess(0x10043a,False,self.pid),'Open exact WeChat process')
        allocated=[]; pending=False; loaded=None
        result={'mode':'--dispatch','pid':self.pid,'target':'filehelper','report_path':str(report_path),
                'code':None,'success':False,'dll_unloaded':False,'cleanup_code':None,
                'native_send_called':False,'bridge_sha256':self.manifest['binary_sha256']}
        def allocate(data):
            ptr=check(K.VirtualAllocEx(process,None,len(data),0x3000,0x04),'Allocate bridge request')
            allocated.append(ptr); buffer=c.create_string_buffer(data); written=c.c_size_t()
            check(K.WriteProcessMemory(process,ptr,buffer,len(data),c.byref(written)),'Write bridge request')
            if written.value!=len(data):raise RuntimeError('Short bridge request write')
            return ptr
        try:
            remote_call(process,remote_system_function(self.pid,b'LoadLibraryW'),allocate((str(self.dll)+'\0').encode('utf-16-le')))
            loaded=modules(self.pid).get(self.dll.name.lower())
            if not loaded or Path(loaded[1]).resolve()!=self.dll:raise RuntimeError('Native file bridge failed to load')
            config=FileConfig()
            config.size,config.pid=c.sizeof(config),self.pid
            config.manager=0; config.log_path=str(report_path);config.text=encoded
            config.target=b'filehelper';config.account=self.account.encode('ascii');config.send=0 if probe else 1
            result['native_send_called']=not probe
            result['code']=remote_call(process,loaded[0]+exports[name],allocate(bytes(config)))
            deadline=time.monotonic()+125
            while result['code']==0 and time.monotonic()<deadline:
                if K.WaitForSingleObject(process,50)==0:raise TimeoutError('WeChat exited before native receipt')
                buf=c.create_string_buffer(96);count=c.c_size_t()
                check(K.ReadProcessMemory(process,loaded[0]+exports[b'WxFileDiagnostics'],buf,96,c.byref(count)),'Read bridge diagnostics')
                if count.value!=96:raise RuntimeError('Short diagnostics read')
                result['diagnostics']=list(struct.unpack('<12q',buf.raw))
                length=result['diagnostics'][9]
                if length:
                    if not 0<length<65536:raise RuntimeError('Invalid native receipt length')
                    payload=c.create_string_buffer(length)
                    check(K.ReadProcessMemory(process,loaded[0]+exports[b'WxFileReport'],payload,length,c.byref(count)),'Read native receipt')
                    if count.value!=length:raise RuntimeError('Short native receipt read')
                    result['report']=json.loads(payload.raw.decode('utf-8'))
                    save_json(report_path,result['report'])
                    break
                if result['diagnostics'][7]:
                    result['error']='Native receipt serialization failed';break
            if result['code']==0 and 'report' not in result:
                result.setdefault('error','Attachment callback timed out; never automatically resend')
        except TimeoutError as exc:
            pending=True;result['error']=str(exc)
        except Exception as exc:
            result['error']=f'{type(exc).__name__}: {exc}'
        finally:
            if loaded and not pending:
                try:
                    code=remote_call(process,loaded[0]+exports[b'WxRemoveSelfTest'],None)
                    result['cleanup_code']=code
                    if code==0:
                        remote_call(process,remote_system_function(self.pid,b'FreeLibrary'),loaded[0])
                        result['dll_unloaded']=self.dll.name.lower() not in modules(self.pid)
                except TimeoutError as exc:pending=True;result['cleanup_error']=str(exc)
                except Exception as exc:result['cleanup_error']=str(exc)
            if not pending:
                for ptr in allocated:K.VirtualFreeEx(process,ptr,0,0x8000)
            else:result['live_request_buffers_retained']=True
            K.CloseHandle(process)
        report=result.get('report',{})
        result['success']=(result['code']==0 and result['cleanup_code']==0 and result['dll_unloaded']
                           and report.get('completion_success') is True and report.get('exception')==0
                           and report.get('target')=='filehelper' and report.get('file_path')==str(path)
                           and report.get('operation')==('file_probe' if probe else 'file_send')
                           and report.get('sent') is (not probe))
        return result
