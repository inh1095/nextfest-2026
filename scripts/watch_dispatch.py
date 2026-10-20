#!/usr/bin/env python3
"""Conservative local GitHub-only fallback for the Next Fest monitor.

This module does not install or enable a timer. It never queries Steam.
--dry-run performs read-only GitHub checks but never creates local state,
dispatches a workflow, or changes a systemd unit.
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import json
import os
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

UTC = timezone.utc
REPO = "inh1095/nextfest-2026"
ACCOUNT = "inh1095"
WORKFLOW = "monitor.yml"
TIMER = "nextfest-monitor-watch.timer"
COOLDOWN = timedelta(minutes=20)
FINAL_GRACE = timedelta(hours=24)
MANIFEST = Path(__file__).resolve().parents[1] / "config/manifest.json"
STATE_FILE = "watch-dispatch.json"
LOCK_FILE = "watch-dispatch.lock"
TOKEN_VARS = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


class SafeError(Exception):
    """A fixed, non-sensitive error code, never a child process message."""


def parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise SafeError("invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except (ValueError, TypeError):
        raise SafeError("invalid_timestamp") from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SafeError("timestamp_timezone_required")
    return parsed.astimezone(UTC)


def stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def state_directory() -> Path:
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".local/state"
    return base / "nextfest-monitor"


def event_window(path: Path) -> tuple[datetime, datetime]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        start = parse_timestamp(data["event"]["starts_at"])
        stop = parse_timestamp(data["collection"]["stops_at"])
    except (OSError, KeyError, TypeError, ValueError, SafeError):
        raise SafeError("manifest_invalid") from None
    if stop <= start:
        raise SafeError("manifest_invalid")
    return start, stop


def read_state(directory: Path) -> dict[str, Any]:
    path = directory / STATE_FILE
    if not path.exists():
        return {}
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(state, dict):
            raise ValueError
        for key in ("final_dispatch_reserved_at", "last_dispatch_attempt_at"):
            if key in state:
                parse_timestamp(state[key])
        return state
    except (OSError, ValueError, TypeError, SafeError):
        raise SafeError("local_state_invalid") from None


def save_state(directory: Path, state: dict[str, Any]) -> None:
    """Commit the reservation durably before issuing a dispatch request."""
    temporary = None
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                         prefix=".watch-", delete=False) as handle:
            temporary = Path(handle.name)
            os.chmod(temporary, 0o600)
            json.dump(state, handle, ensure_ascii=False, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, directory / STATE_FILE)
        temporary = None
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError:
        raise SafeError("local_reservation_failed") from None
    finally:
        if temporary is not None:
            with contextlib.suppress(OSError):
                temporary.unlink()


@contextlib.contextmanager
def local_lock(directory: Path, dry_run: bool):
    """Dry runs may lock an existing file, but never create a path."""
    fd = None
    acquired = False
    try:
        path = directory / LOCK_FILE
        if dry_run:
            if not path.exists():
                yield True
                return
            fd = os.open(path, os.O_RDONLY)
        else:
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            yield False
            return
        yield True
    except OSError:
        raise SafeError("local_lock_failed") from None
    finally:
        if fd is not None:
            if acquired:
                with contextlib.suppress(OSError):
                    fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def clean_environment() -> dict[str, str]:
    env = os.environ.copy()
    for name in TOKEN_VARS:
        env.pop(name, None)
    # Avoid inherited CLI tracing accidentally exposing API request headers.
    env.pop("GH_DEBUG", None)
    env["GH_PROMPT_DISABLED"] = "1"
    return env


class GitHub:
    """All credentials are captured, then passed only through child GH_TOKEN."""

    def __init__(self, runner: Callable = subprocess.run):
        self.runner = runner
        self.env: dict[str, str] | None = None

    def _command(self, args: list[str], env: dict[str, str], failure: str) -> str:
        try:
            result = self.runner(args, env=env, capture_output=True, text=True,
                                 timeout=30, check=False)
        except (OSError, subprocess.SubprocessError):
            raise SafeError(failure) from None
        if result.returncode != 0:
            raise SafeError(failure)
        return result.stdout

    def authenticate(self) -> None:
        env = clean_environment()
        token = self._command(["gh", "auth", "token", "--hostname", "github.com", "--user", ACCOUNT],
                              env, "github_auth_failed").strip()
        if not token or any(char.isspace() for char in token):
            raise SafeError("github_auth_failed")
        self.env = {**env, "GH_TOKEN": token}

    def _api(self, path: str, method: str = "GET") -> Any:
        if self.env is None:
            self.authenticate()
        args = ["gh", "api", "--hostname", "github.com", "--method", method, path]
        if method == "POST":
            args.extend(["-f", "ref=main", "--silent"])
        output = self._command(args, self.env, "github_request_failed")
        if method == "POST":
            return None
        try:
            data = json.loads(output)
        except (ValueError, TypeError):
            raise SafeError("github_json_invalid") from None
        if not isinstance(data, dict):
            raise SafeError("github_json_invalid")
        return data

    def workflow(self) -> str:
        data = self._api(f"repos/{REPO}/actions/workflows/{WORKFLOW}")
        state = data.get("state")
        if not isinstance(state, str) or not state:
            raise SafeError("github_workflow_invalid")
        return state

    def runs(self) -> list[dict[str, Any]]:
        data = self._api(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?per_page=10")
        runs = data.get("workflow_runs")
        if not isinstance(runs, list) or any(not isinstance(run, dict) for run in runs):
            raise SafeError("github_runs_invalid")
        return runs

    def dispatch(self) -> None:
        self._api(f"repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches", "POST")


def decide(now: datetime, start: datetime, stop: datetime, workflow_state: str,
           runs: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    """Pure policy; every non-completed run blocks, regardless of event type."""
    if now >= stop + FINAL_GRACE:
        return {"action": "stop_timer", "reason": "hard_stop_reached"}
    if now < start:
        return {"action": "skip", "reason": "event_not_started"}
    if workflow_state.startswith("disabled_"):
        return {"action": "stop_timer" if now >= stop else "skip", "reason": "workflow_disabled"}
    if workflow_state != "active":
        return {"action": "skip", "reason": "workflow_not_active"}
    if now >= stop and state.get("final_dispatch_reserved_at"):
        return {"action": "skip", "reason": "final_dispatch_already_reserved"}
    for run in runs:
        status = run.get("status")
        if not isinstance(status, str) or not status:
            raise SafeError("github_run_status_invalid")
        if status != "completed":
            return {"action": "skip", "reason": "workflow_run_pending"}
    for run in runs:
        event = run.get("event")
        if not isinstance(event, str):
            raise SafeError("github_run_event_invalid")
        if event in ("workflow_dispatch", "schedule"):
            try:
                created = parse_timestamp(run.get("created_at"))
            except SafeError:
                raise SafeError("github_run_timestamp_invalid") from None
            if now - created < COOLDOWN:
                return {"action": "skip", "reason": "recent_collecting_run"}
    # Also protect against a successful dispatch that has not appeared in the API yet.
    attempted = state.get("last_dispatch_attempt_at")
    if attempted and now - parse_timestamp(attempted) < COOLDOWN:
        return {"action": "skip", "reason": "recent_local_dispatch_attempt"}
    return {"action": "dispatch", "reason": "final_archive_once" if now >= stop else "schedule_fallback",
            "final_archive": now >= stop}


def stop_timer(runner: Callable = subprocess.run) -> None:
    try:
        result = runner(["systemctl", "--user", "disable", "--now", TIMER],
                        capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError):
        raise SafeError("timer_stop_failed") from None
    if result.returncode != 0:
        raise SafeError("timer_stop_failed")


def run_once(*, dry_run: bool = False, now: datetime | None = None,
             manifest: Path = MANIFEST, directory: Path | None = None,
             github: GitHub | None = None, timer_stop: Callable = stop_timer) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise SafeError("timestamp_timezone_required")
    now = now.astimezone(UTC)
    directory = directory or state_directory()
    start, stop = event_window(manifest)
    base = {"checked_at": stamp(now), "repository": REPO, "workflow": WORKFLOW,
            "dry_run": dry_run, "event_stops_at": stamp(stop)}
    with local_lock(directory, dry_run) as acquired:
        if not acquired:
            return {**base, "action": "skip", "reason": "local_watcher_running"}
        # The hard boundary and pre-event guard never need GitHub authentication.
        if now >= stop + FINAL_GRACE:
            decision = {"action": "stop_timer", "reason": "hard_stop_reached"}
        elif now < start:
            decision = {"action": "skip", "reason": "event_not_started"}
        else:
            state = read_state(directory)
            github = github or GitHub()
            workflow_state = github.workflow()
            runs = github.runs() if workflow_state == "active" else []
            decision = decide(now, start, stop, workflow_state, runs, state)
        if decision["action"] == "stop_timer":
            if dry_run:
                decision["action"] = "would_stop_timer"
            else:
                timer_stop()
                decision["action"] = "timer_stopped"
        elif decision["action"] == "dispatch":
            if dry_run:
                decision["action"] = "would_dispatch"
            else:
                state["schema_version"] = 1
                state["last_dispatch_attempt_at"] = stamp(now)
                if decision["final_archive"]:
                    state["final_dispatch_reserved_at"] = stamp(now)
                    state["final_dispatch_for_stop"] = stamp(stop)
                save_state(directory, state)
                github.dispatch()
                decision["action"] = "dispatched"
        return {**base, **decision}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Read checks only; no dispatch, state writes, or timer changes")
    args = parser.parse_args(argv)
    try:
        result = run_once(dry_run=args.dry_run)
    except SafeError as error:
        result = {"action": "error", "reason": str(error), "dry_run": args.dry_run,
                  "repository": REPO, "workflow": WORKFLOW}
    except Exception:
        # No raw exceptions, tokens, captured stderr, or API bodies reach output.
        result = {"action": "error", "reason": "watcher_internal_error", "dry_run": args.dry_run,
                  "repository": REPO, "workflow": WORKFLOW}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 1 if result["action"] == "error" else 0


if __name__ == "__main__":
    raise SystemExit(main())
