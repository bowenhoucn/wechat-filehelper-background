"""Local state, integrity checks and a process-scoped cross-thread lock."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

SKILL = Path(__file__).resolve().parent.parent
LOCK = json.loads((SKILL / "references/runtime-lock.json").read_text(encoding="utf-8"))


def now():
    return datetime.now(timezone.utc).isoformat()


def state_home():
    # One ledger per Windows user, independent of Codex home/install location.
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise RuntimeError("LOCALAPPDATA is missing; Windows desktop is required")
    return Path(base) / "CodexWeChatFileHelper"


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def save_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    with temp.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


@contextmanager
def exclusive_lock(home):
    """The OS releases this byte lock on process exit; never delete stale locks."""
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    handle = (home / "operation.lock").open("a+b")
    acquired = False
    try:
        handle.seek(0, os.SEEK_END)
        if not handle.tell():
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:  # Offline tests only; native sending remains Windows-only.
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RuntimeError("Another filehelper operation is active; do not start a parallel sender") from exc
        acquired = True
        yield
    finally:
        if acquired:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def hidden_run(argv, **kwargs):
    options = {"check": True, "capture_output": True, "text": True,
               "encoding": "utf-8", "errors": "replace", "shell": False}
    if os.name == "nt":
        options["creationflags"] = subprocess.CREATE_NO_WINDOW
    options.update(kwargs)
    return subprocess.run([str(x) for x in argv], **options)


def runtime_paths(home):
    root = Path(home) / "runtime" / LOCK["commit"]
    return root / "helper", root / "deps"


def verify_files(root, hashes):
    for relative, expected in hashes.items():
        target = Path(root) / relative
        if not target.is_file() or sha256(target) != expected:
            raise RuntimeError(f"Runtime integrity mismatch: {relative}; run bootstrap, do not bypass hashes")


def verify_runtime(home):
    repo, deps = runtime_paths(home)
    verify_files(repo, LOCK["files"])
    verify_files(deps, LOCK["dependency_files"])
    return repo, deps


def require_windows():
    if os.name != "nt" or sys.maxsize <= 2**32:
        raise RuntimeError("Windows with 64-bit Python 3.10+ is required")
