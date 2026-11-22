"""Read-only desktop compatibility diagnosis. Candidate mappings never enable send."""
from pathlib import Path
import ctypes as c
import json
from common import LOCK, SKILL, sha256

class CompatibilityError(RuntimeError):
    def __init__(self, details):
        self.details = details
        cores = details.get('unsupported_cores', [])
        versions = ', '.join(sorted({x['wechat_version'] for x in cores})) or 'unknown'
        super().__init__(f'Desktop WeChat {versions} has no validated ordinary-file adapter; '
                         'this is not evidence that the user is logged out. No injection or send attempted.')

def file_version(path):
    lib = c.WinDLL('version', use_last_error=True)
    lib.GetFileVersionInfoSizeW.argtypes = [c.c_wchar_p, c.POINTER(c.c_uint32)]
    lib.GetFileVersionInfoSizeW.restype = c.c_uint32
    lib.GetFileVersionInfoW.argtypes = [c.c_wchar_p, c.c_uint32, c.c_uint32, c.c_void_p]
    lib.VerQueryValueW.argtypes = [c.c_void_p, c.c_wchar_p, c.POINTER(c.c_void_p), c.POINTER(c.c_uint32)]
    dummy = c.c_uint32()
    size = lib.GetFileVersionInfoSizeW(str(path), c.byref(dummy))
    if not size: return 'unknown'
    data = c.create_string_buffer(size)
    if not lib.GetFileVersionInfoW(str(path), 0, size, data): return 'unknown'
    pointer, length = c.c_void_p(), c.c_uint32()
    if not lib.VerQueryValueW(data, '\\', c.byref(pointer), c.byref(length)) or length.value < 16:
        return 'unknown'
    fields = c.cast(pointer, c.POINTER(c.c_uint32))
    if fields[0] != 0xfeef04bd: return 'unknown'
    return '.'.join(str(x) for x in (fields[2] >> 16, fields[2] & 65535, fields[3] >> 16, fields[3] & 65535))

def classify_core(path, digest=None):
    path = Path(path)
    digest = digest or sha256(path)
    size = path.stat().st_size
    result = {'path': str(path), 'wechat_version': file_version(path), 'bytes': size,
              'sha256': digest, 'attachment_adapter_validated': False}
    registered = next((p for p in LOCK['validated_cores'] if p['size'] == size and p['sha256'] == digest), None)
    if registered:
        result['attachment_adapter_validated'] = True
        result['wechat_version'] = registered['wechat_version']
        return result
    candidate_path = SKILL / 'references/candidate-4.2.0.53.json'
    if not candidate_path.is_file():
        result.update(candidate_mapping_found=False, candidate_metadata_missing=True,
                      remediation='Reinstall the complete skill including references and assets')
        return result
    candidate = json.loads(candidate_path.read_text(encoding='utf-8'))
    p = candidate['profile']
    if p['size'] == size and p['sha256'] == digest:
        result.update(candidate_mapping_found=True,
                      candidate_scope=candidate.get('status', 'text/image, not ordinary-file attachments'),
                      missing_interfaces=candidate.get('unmapped_attachment_interfaces', []),
                      static_attachment_candidates=candidate.get('static_attachment_candidates', {}),
                      pending_validation=candidate.get('pending_validation', []),
                      source_commit=candidate['source']['commit'])
    else:
        result['candidate_mapping_found'] = False
    return result
