"""Install pinned upstream runtime outside the skill; never touches WeChat UI."""
from pathlib import Path
import argparse
import json
import sys
import uuid

from common import (LOCK, SKILL, exclusive_lock, hidden_run, now, require_windows,
                    runtime_paths, save_json, state_home, verify_files, verify_runtime)


def install(home, source=None):
    require_windows()
    with exclusive_lock(home):
        repo, deps = runtime_paths(home)
        if repo.exists() or deps.exists():
            verify_runtime(home)
            return {"status": "runtime_ready", "runtime": str(repo), "reused": True}
        scratch = Path(home) / "setup" / uuid.uuid4().hex
        staging = scratch / "helper"
        staging.parent.mkdir(parents=True, exist_ok=True)
        # Git is launched with no console, no shell and no interactive prompts.
        import os
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
        hidden_run(["git", "init", staging], env=env, timeout=60)
        origin = str(Path(source).resolve()) if source else LOCK["repository"]
        hidden_run(["git", "-C", staging, "remote", "add", "origin", origin], env=env, timeout=30)
        hidden_run(["git", "-C", staging, "fetch", "--depth=1", "origin", LOCK["commit"]], env=env, timeout=180)
        hidden_run(["git", "-C", staging, "-c", "core.autocrlf=false", "checkout", "--detach", "FETCH_HEAD"], env=env, timeout=60)
        actual = hidden_run(["git", "-C", staging, "rev-parse", "HEAD"], timeout=30).stdout.strip()
        if actual != LOCK["commit"]:
            raise RuntimeError("Pinned source commit mismatch")
        verify_files(staging, LOCK["files"])
        staged_deps = scratch / "deps"
        hidden_run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check",
                    "--no-input", "--no-deps", "--only-binary=:all:", "--require-hashes",
                    "--target", staged_deps, "-r", SKILL / "references/requirements.lock"], timeout=180)
        verify_files(staged_deps, LOCK["dependency_files"])
        # Whole runtime is published atomically; a failed setup remains for diagnosis.
        destination = repo.parent
        destination.parent.mkdir(parents=True, exist_ok=True)
        scratch.replace(destination)
        save_json(destination / "installation.json", {
            "time": now(), "commit": actual, "source": LOCK["repository"],
            "license": LOCK["upstream_license"], "status": "runtime_ready"})
        return {"status": "runtime_ready", "runtime": str(repo), "reused": False}


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
