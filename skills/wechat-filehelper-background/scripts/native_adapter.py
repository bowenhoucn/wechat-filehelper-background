"""Small file-only interface around the hash-locked native upstream runtime."""
import hashlib
from pathlib import Path
import sys

from common import LOCK, require_windows, sha256, verify_runtime


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
        for pid in wechat_candidates():
            try:
                loaded = modules(pid)
                core = loaded.get("weixin.dll")
                if not core:
                    continue
                profile = next((p for p in LOCK["validated_cores"]
                                if Path(core[1]).stat().st_size == p["size"]
                                and sha256(core[1]) == p["sha256"]), None)
                if not profile:
                    unsupported.append(pid)
                    continue
                account = inspect_account(pid)
                if account:
                    candidates.append((pid, account, profile))
            except OSError:
                continue
        if len(candidates) != 1 or unsupported:
            raise RuntimeError(f"Need one compatible logged-in account; compatible={len(candidates)}, unsupported={len(unsupported)}")
        self.pid, self.account, profile = candidates[0]
        self.identity = {"account_sha256": hashlib.sha256(self.account.encode()).hexdigest(),
                         "pid": self.pid, "wechat_version": profile["wechat_version"],
                         "core_sha256": profile["sha256"], "upstream_commit": LOCK["commit"]}
        self.check()

    def check(self):
        loaded = self.modules(self.pid)
        if any(name.endswith("bridge.dll") for name in loaded):
            raise RuntimeError("A native bridge is already active; do not unload another sender's component")
        core = loaded.get("weixin.dll")
        if not core or sha256(core[1]) != self.identity["core_sha256"]:
            raise RuntimeError("WeChat core changed")
        if self.inspect_account(self.pid) != self.account:
            raise RuntimeError("Logged-in account changed")

    def dispatch(self, path, *, probe):
        self.check()
        return self.run("--dispatch", pid=self.pid, bridge_path=self.dll,
                        target="filehelper", file_path=str(path), file_probe=probe,
                        account=self.account, preserve_report=True)
