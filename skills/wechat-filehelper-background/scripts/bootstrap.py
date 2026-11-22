"""Install the bundled, hash-locked runtime offline; preserve old runtime on repair."""
from pathlib import Path
import argparse
import json
import sys
import uuid
import zipfile

from common import (LOCK, SKILL, exclusive_lock, hidden_run, now, require_windows,
                    runtime_paths, save_json, sha256, state_home, verify_files, verify_runtime)


def extract_bundle(archive, destination, expected_hash):
    if not archive.is_file():
        raise RuntimeError("Bundled runtime is missing; reinstall the complete skill, including assets")
    if sha256(archive) != expected_hash:
        raise RuntimeError("Bundled runtime hash mismatch; refusing extraction")
    destination = Path(destination).resolve()
    with zipfile.ZipFile(archive) as bundle:
        for item in bundle.infolist():
            relative = Path(item.filename)
            target = (destination / relative).resolve()
            if (relative.is_absolute() or ':' in item.filename or '\\' in item.filename
                    or '..' in relative.parts or not target.is_relative_to(destination)
                    or (item.external_attr >> 16) & 0o170000 == 0o120000):
                raise RuntimeError("Invalid bundled archive path")
        bundle.extractall(destination)


def install(home, source=None):
    require_windows()
    with exclusive_lock(home):
        repo, deps = runtime_paths(home)
        previous_error = None
        if repo.exists() or deps.exists():
            try:
                verify_runtime(home)
                return {"status": "runtime_ready", "runtime": str(repo), "reused": True}
            except RuntimeError as exc:
                previous_error = str(exc)
        scratch = Path(home) / "setup" / uuid.uuid4().hex
        staging = scratch / "helper"
        staging.parent.mkdir(parents=True, exist_ok=True)
        if source:
            # Explicit local recovery source; no network fetch and no branch drift.
            import os
            source = Path(source).resolve(strict=True)
            if not source.is_dir():
                raise RuntimeError("--source must be a local upstream Git checkout")
            env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
            archive = scratch / "local-recovery.zip"
            hidden_run(["git", "-c", "core.autocrlf=false", "-C", source, "archive", "--format=zip", "--output", archive,
                        LOCK["commit"], "native", "wxbot_framework", "LICENSE", "THIRD_PARTY_NOTICES.md"],
                       env=env, timeout=60)
            extract_bundle(archive, staging, LOCK["bundle"]["sha256"])
        else:
            extract_bundle(SKILL / LOCK["bundle"]["path"], staging, LOCK["bundle"]["sha256"])
        verify_files(staging, LOCK["files"])
        staged_deps = scratch / "deps"
        for relative, expected in LOCK["bundled_dependencies"].items():
            verify_files(SKILL, {relative: expected})
        hidden_run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-input", "--no-index", "--find-links", SKILL / "assets",
                    "--no-deps", "--only-binary=:all:", "--require-hashes",
                    "--target", staged_deps, "-r", SKILL / "references/requirements.lock"], timeout=180)
        verify_files(staged_deps, LOCK["dependency_files"])
        # Whole runtime is published atomically; a failed setup remains for diagnosis.
        destination = repo.parent
        destination.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if destination.exists():
            backup = Path(home) / "runtime-quarantine" / uuid.uuid4().hex
            backup.parent.mkdir(parents=True, exist_ok=True)
            destination.replace(backup)
        try:
            scratch.replace(destination)
        except BaseException:
            if backup and not destination.exists():
                backup.replace(destination)
            raise
        save_json(destination / "installation.json", {
            "time": now(), "commit": LOCK["commit"], "source": "bundled_hash_locked_archive",
            "original_repository": LOCK["repository"], "bundle_sha256": LOCK["bundle"]["sha256"],
            "license": LOCK["upstream_license"], "status": "runtime_ready",
            "preserved_previous_runtime": str(backup) if backup else None, "previous_error": previous_error})
        return {"status": "runtime_ready", "runtime": str(repo), "reused": False,
                "preserved_previous_runtime": str(backup) if backup else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", help="Optional existing upstream Git checkout; still checks commit and hashes")
    args = parser.parse_args()
    try:
        result = install(state_home(), args.source)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"status": "setup_failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
