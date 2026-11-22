"""Background filehelper sender. No UI automation and no automatic retransmission."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import sys
import uuid

from common import exclusive_lock, now, save_json, sha256, state_home

BLOCKING = {"preparing", "dispatch_started", "needs_reconciliation",
            "native_submission_accepted", "user_confirmed_received", "historical_submission_imported"}


class Ledger:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.home / "ledger.sqlite3", timeout=5)
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("""CREATE TABLE IF NOT EXISTS attempts (
            id TEXT PRIMARY KEY, account TEXT NOT NULL, digest TEXT NOT NULL,
            status TEXT NOT NULL, created TEXT NOT NULL, body TEXT NOT NULL)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS content_idx ON attempts(account, digest)")
        self.db.commit()

    def close(self):
        self.db.close()

    def put(self, receipt):
        # Commit the durable reservation/state before invoking any native mutation.
        self.db.execute("INSERT OR REPLACE INTO attempts VALUES(?,?,?,?,?,?)", (
            receipt["id"], receipt["account_sha256"], receipt["sha256"],
            receipt["status"], receipt["created_at"], json.dumps(receipt, ensure_ascii=False)))
        self.db.commit()
        save_json(receipt["receipt_path"], receipt)

    def prior(self, account, digest):
        rows = self.db.execute("SELECT body FROM attempts WHERE account=? AND digest=? ORDER BY created DESC",
                               (account, digest)).fetchall()
        return next((r for (text,) in rows if (r := json.loads(text))["status"] in BLOCKING), None)

    def get(self, attempt_id=None):
        if attempt_id:
            rows = self.db.execute("SELECT body FROM attempts WHERE id=?", (attempt_id,)).fetchall()
        else:
            rows = self.db.execute("SELECT body FROM attempts ORDER BY created DESC LIMIT 20").fetchall()
        return [json.loads(row[0]) for row in rows]


def snapshot(source, directory):
    value = os.fspath(source)
    if value.startswith(("\\\\", "//")) or "://" in value:
        raise ValueError("Specify a local file, not a URL or network share")
    source = Path(value).resolve(strict=True)
    remaining = str(source)[len(source.drive):] if os.name == "nt" else str(source)
    if ":" in remaining:
        raise ValueError("NTFS alternate data streams are not supported")
    if os.name == "nt":
        import ctypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
        if str(source).startswith("\\\\") or kernel.GetDriveTypeW(source.anchor) == 4:
            raise ValueError("Mapped network files are not supported")
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / source.name
    if len(str(target).encode("utf-8")) > 1023 or len(str(target).encode("utf-16-le")) // 2 >= 260:
        raise ValueError("Snapshot path is too long; shorten the input filename")
    h = hashlib.sha256()
    with source.open("rb") as src:
        before = os.fstat(src.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0:
            raise ValueError("Only nonempty regular files can be sent")
        if shutil.disk_usage(directory).free < before.st_size * 2 + 16 * 1024**2:
            raise RuntimeError("Insufficient local disk space for snapshot and attachment staging")
        with target.open("xb") as dst:
            count = 0
            for chunk in iter(lambda: src.read(1024 * 1024), b""):
                h.update(chunk)
                dst.write(chunk)
                count += len(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        after = os.fstat(src.fileno())
    current = source.stat()
    key = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns)
    if count != before.st_size or key(before) != key(after) or key(after) != key(current):
        raise RuntimeError("Source changed while snapshotting; nothing was submitted")
    return target, {"source_path": str(source), "filename": source.name,
                    "sha256": h.hexdigest(), "bytes": count, "snapshot_path": str(target)}


@contextmanager
def protect_snapshot(path):
    """Deny concurrent writes/deletion while native code reads the snapshot."""
    if os.name != "nt":
        with Path(path).open("rb"):
            yield
        return
    import ctypes as c
    from ctypes import wintypes as w
    kernel = c.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, c.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
    kernel.CreateFileW.restype = w.HANDLE
    kernel.CloseHandle.argtypes = [w.HANDLE]
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x80, None)
    if handle == c.c_void_p(-1).value:
        raise c.WinError(c.get_last_error())
    try:
        yield
    finally:
        kernel.CloseHandle(handle)


def accepted(result, path, size, *, probe):
    report = result.get("report", {})
    return (result.get("success") is True and result.get("code") == 0
            and result.get("cleanup_code") == 0 and result.get("dll_unloaded") is True
            and report.get("completion_success") is True and report.get("target") == "filehelper"
            and report.get("operation") == ("file_probe" if probe else "file_send")
            and report.get("message_type") == 49 and report.get("app_type") == 6
            and report.get("sent") is (not probe) and report.get("file_path") == str(path)
            and report.get("bytes") == size and report.get("native_status") == 0
            and report.get("native_status_high") == 0)


def send(source, home, adapter_factory, *, resend_reason=None):
    home = Path(home)
    with exclusive_lock(home):
        adapter = adapter_factory(home)
        attempt_id = uuid.uuid4().hex
        staged, artifact = snapshot(source, home / "snapshots" / attempt_id)
        ledger = Ledger(home)
        try:
            previous = ledger.prior(adapter.identity["account_sha256"], artifact["sha256"])
            if previous and not resend_reason:
                # Delete only this new, unused snapshot. The old evidence is untouched.
                staged.unlink()
                staged.parent.rmdir()
                return {"status": "duplicate_blocked", "previous_status": previous["status"],
                        "receipt_path": previous["receipt_path"], "id": previous["id"],
                        "message": "No new send; an earlier submission or uncertain attempt exists"}
            receipt = {"schema_version": 1, "id": attempt_id, "created_at": now(),
                       "recipient": "filehelper", "status": "preparing", **adapter.identity, **artifact,
                       "receipt_path": str(home / "receipts" / (attempt_id + ".json")),
                       "server_upload_completion_independently_verified": False,
                       "resend_reason": resend_reason,
                       "previous_attempt_id": previous["id"] if previous else None}
            ledger.put(receipt)
            dispatch_started = False
            try:
                with protect_snapshot(staged):
                    if sha256(staged) != artifact["sha256"]:
                        raise RuntimeError("Snapshot integrity mismatch")
                    probe = adapter.dispatch(staged, probe=True)
                    probe_path = home / "receipts" / (attempt_id + ".probe.json")
                    save_json(probe_path, probe)
                    receipt["probe_path"] = str(probe_path)
                    if not accepted(probe, staged, artifact["bytes"], probe=True):
                        raise RuntimeError("Attachment probe did not pass; no send dispatched")
                    adapter.check()
                    receipt.update(status="dispatch_started", dispatch_started_at=now())
                    ledger.put(receipt)
                    dispatch_started = True
                    result = adapter.dispatch(staged, probe=False)
                    raw_path = home / "receipts" / (attempt_id + ".native.json")
                    save_json(raw_path, result)
                    receipt.update(native_result_path=str(raw_path), completed_at=now(),
                                   bridge_unloaded=result.get("dll_unloaded"),
                                   status="native_submission_accepted" if accepted(result, staged, artifact["bytes"], probe=False)
                                   else "needs_reconciliation")
                    report = result.get("report", {})
                    receipt["native_summary"] = {k: report.get(k) for k in (
                        "sent", "native_status", "native_status_high", "completion_success", "bytes")}
                    prepared = report.get("prepared_path")
                    # Missing/changed temp content must not downgrade an accepted send into a retry.
                    if prepared and Path(prepared).is_file():
                        try:
                            receipt["staged_copy_sha256_verified"] = sha256(prepared) == artifact["sha256"]
                        except OSError:
                            receipt["staged_copy_sha256_verified"] = None
                    ledger.put(receipt)
                    return receipt
            except BaseException as exc:
                receipt.update(status="needs_reconciliation" if dispatch_started else "failed_before_dispatch",
                               error=f"{type(exc).__name__}: {exc}", completed_at=now())
                ledger.put(receipt)
                if not isinstance(exc, Exception):
                    raise
                return receipt
        finally:
            ledger.close()


def import_receipt(receipt_path, attempt_path, home):
    """Import a prior one-shot sender's accepted receipt without sending anything."""
    receipt_path, attempt_path = Path(receipt_path).resolve(), Path(attempt_path).resolve()
    raw = json.loads(receipt_path.read_text(encoding="utf-8-sig"))
    attempt = json.loads(attempt_path.read_text(encoding="utf-8-sig"))
    if (raw.get("recipient_id") != "filehelper" or attempt.get("recipient") != "filehelper"
            or raw.get("status") != "native_submission_accepted"
            or attempt.get("status") != "native_submission_accepted"
            or raw.get("sha256") != attempt.get("sha256") or raw.get("bytes") != attempt.get("bytes")):
        raise ValueError("Legacy receipt and attempt must agree on recipient, accepted status and artifact")
    for value in (raw.get("sha256"), attempt.get("account_sha256")):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Missing or invalid artifact/account hash")
    with exclusive_lock(home):
        ledger = Ledger(home)
        try:
            prior = ledger.prior(attempt["account_sha256"], raw["sha256"])
            if prior:
                return {"status": "already_imported_or_reserved", "receipt_path": prior["receipt_path"]}
            attempt_id = uuid.uuid4().hex
            entry = {"schema_version": 1, "id": attempt_id, "status": "historical_submission_imported",
                     "created_at": now(), "recipient": "filehelper", "sha256": raw["sha256"],
                     "bytes": raw["bytes"], "account_sha256": attempt["account_sha256"],
                     "source_path": raw.get("pdf"), "legacy_receipt": str(receipt_path),
                     "legacy_attempt": str(attempt_path), "legacy_receipt_sha256": sha256(receipt_path),
                     "legacy_attempt_sha256": sha256(attempt_path),
                     "receipt_path": str(Path(home) / "receipts" / (attempt_id + ".json")),
                     "server_upload_completion_independently_verified": False}
            ledger.put(entry)
            return entry
        finally:
            ledger.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    send_parser = sub.add_parser("send", help="Send one explicitly requested local file")
    send_parser.add_argument("--file", required=True)
    send_parser.add_argument("--resend-reason", help="Only with the user's explicit request to send the same content again")
    sub.add_parser("doctor", help="Read-only runtime/core/account check; no native injection or send")
    status_parser = sub.add_parser("status", help="Read local ledger; does not assert server delivery")
    status_parser.add_argument("--id")
    importer = sub.add_parser("import-receipt", help="Import a verified legacy receipt and attempt for duplicate prevention")
    importer.add_argument("--receipt", required=True)
    importer.add_argument("--attempt", required=True)
    args = parser.parse_args()
    try:
        home = state_home()
        if args.command == "status":
            with exclusive_lock(home):
                ledger = Ledger(home)
                try:
                    result = {"status": "local_records", "attempts": ledger.get(args.id)}
                finally:
                    ledger.close()
        elif args.command == "import-receipt":
            result = import_receipt(args.receipt, args.attempt, home)
        else:
            from native_adapter import NativeAdapter
            if args.command == "doctor":
                with exclusive_lock(home):
                    adapter = NativeAdapter(home)
                    result = {"status": "ready", **adapter.identity, "state_home": str(home),
                              "note": "Read-only check; no file sent"}
            else:
                reason = args.resend_reason
                if reason is not None and not reason.strip():
                    raise ValueError("A resend needs a nonempty user-authorized reason")
                result = send(args.file, home, NativeAdapter, resend_reason=reason)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 2 if result.get("status") in {"needs_reconciliation", "failed_before_dispatch"} else 0
    except Exception as exc:
        result = {"status": "blocked_before_dispatch", "error": str(exc)}
        if getattr(exc, "details", None):
            result["compatibility"] = exc.details
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
