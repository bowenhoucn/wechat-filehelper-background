"""Small file-only interface around the hash-locked native upstream runtime."""
import hashlib
from pathlib import Path
import sys

from common import LOCK, require_windows, sha256, verify_runtime
from compatibility import CompatibilityError, classify_core


class NativeAdapter:
    def __init__(self, home):
        require_windows()
        repo, deps = verify_runtime(home)
        sys.path[:0] = [str(deps), str(repo), str(repo / "native")]
        from run_selftest import TEXT_DLL, modules, run, wechat_candidates
        from text_service import inspect_account
        self.run, self.modules, self.inspect_account = run, modules, inspect_account
        self.dll = TEXT_DLL
        # Check the exact core before reading version-dependent account offsets.
        candidates = []
        unsupported = []
        fingerprints = {}
        for pid in wechat_candidates():
            try:
                loaded = modules(pid)
                core = loaded.get("weixin.dll")
                if not core:
                    continue
                core_path = str(Path(core[1]).resolve())
                if core_path not in fingerprints:
                    fingerprints[core_path] = sha256(core_path)
                digest = fingerprints[core_path]
                profile = next((p for p in LOCK["validated_cores"]
                                if Path(core_path).stat().st_size == p["size"]
                                and digest == p["sha256"]), None)
                if not profile:
                    unsupported.append({"pid": pid, **classify_core(core_path, digest)})
                    continue
                if profile.get('adapter') == 'native_42053':
                    from native_42053 import inspect_account as inspect_new_account
                    account = inspect_new_account(pid)
                else:
                    account = inspect_account(pid)
                if account:
                    candidates.append((pid, account, profile))
            except OSError:
                continue
        if unsupported:
            raise CompatibilityError({"unsupported_cores": unsupported,
                "compatible_account_count": len(candidates), "native_injection_attempted": False,
                "native_send_called": False, "route": "logged_in_desktop_only"})
        if len(candidates) != 1:
            raise RuntimeError(f"Need one compatible logged-in account; compatible={len(candidates)}, unsupported={len(unsupported)}")
        self.pid, self.account, profile = candidates[0]
        if profile.get('adapter') == 'native_42053':
            from native_42053 import Adapter42053
            self._delegate = Adapter42053(home, self.pid)
            self.identity = {**self._delegate.identity, 'upstream_commit': LOCK['commit']}
            return
        self.identity = {"account_sha256": hashlib.sha256(self.account.encode()).hexdigest(),
                         "pid": self.pid, "wechat_version": profile["wechat_version"],
                         "core_sha256": profile["sha256"], "upstream_commit": LOCK["commit"]}
        self.check()

    def check(self):
        if hasattr(self, '_delegate'):
            return self._delegate.check()
        loaded = self.modules(self.pid)
        if any(name.endswith("bridge.dll") for name in loaded):
            raise RuntimeError("A native bridge is already active; do not unload another sender's component")
        core = loaded.get("weixin.dll")
        if not core or sha256(core[1]) != self.identity["core_sha256"]:
            raise RuntimeError("WeChat core changed")
        if self.inspect_account(self.pid) != self.account:
            raise RuntimeError("Logged-in account changed")

    def dispatch(self, path, *, probe):
        if hasattr(self, '_delegate'):
            return self._delegate.dispatch(path, probe=probe)
        self.check()
        return self.run("--dispatch", pid=self.pid, bridge_path=self.dll,
                        target="filehelper", file_path=str(path), file_probe=probe,
                        account=self.account, preserve_report=True)
