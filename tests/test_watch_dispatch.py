"""Offline watchdog policy tests; no GitHub, Steam, dispatch, or systemd calls."""
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import watch_dispatch as watch


class WatchDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.directory = self.root / "state"
        self.start = watch.parse_timestamp("2026-10-19T17:00:00Z")
        self.stop = watch.parse_timestamp("2026-10-26T17:00:00Z")
        self.now = self.start + timedelta(hours=2)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({"event": {"starts_at": watch.stamp(self.start)},
                                            "collection": {"stops_at": watch.stamp(self.stop)}}))
        self.github = Mock()
        self.github.workflow.return_value = "active"
        self.github.runs.return_value = []
        self.timer = Mock()

    def run_watch(self, **kwargs):
        return watch.run_once(now=kwargs.pop("now", self.now), manifest=self.manifest,
                              directory=self.directory, github=self.github,
                              timer_stop=self.timer, **kwargs)

    def policy(self, *, now=None, status="active", runs=None, state=None):
        return watch.decide(now or self.now, self.start, self.stop, status,
                            runs or [], state or {})

    def completed(self, minutes=21, event="schedule", **updates):
        return {"id": 1, "status": "completed", "event": event,
                "created_at": watch.stamp(self.now - timedelta(minutes=minutes)), **updates}

    def test_timestamp_converts_offsets_to_utc(self):
        utc = watch.parse_timestamp("2026-10-27T02:00:00+09:00")
        self.assertEqual(utc, self.stop)
        self.assertEqual(watch.stamp(utc), "2026-10-26T17:00:00Z")
        self.assertEqual(watch.parse_timestamp("2026-10-26T12:00:00-05:00"), self.stop)
        for value in ("2026-10-26T17:00:00", "not-a-time", None):
            with self.subTest(value=value), self.assertRaises(watch.SafeError):
                watch.parse_timestamp(value)

    def test_before_event_never_queries_github_or_dispatches(self):
        result = self.run_watch(now=self.start-timedelta(seconds=1), dry_run=True)
        self.assertEqual(result["reason"], "event_not_started")
        self.github.workflow.assert_not_called()
        self.github.dispatch.assert_not_called()
        self.assertFalse(self.directory.exists())

    def test_every_non_completed_status_blocks_for_every_event(self):
        for status in ("in_progress", "queued", "waiting", "pending", "requested", "running", "unknown"):
            for event in ("push", "workflow_dispatch", "schedule", "repository_dispatch"):
                with self.subTest(status=status, event=event):
                    result = self.policy(runs=[self.completed(event=event, status=status)])
                    self.assertEqual(result["reason"], "workflow_run_pending")

    def test_completed_schedule_and_dispatch_twenty_minute_boundary(self):
        for event in ("schedule", "workflow_dispatch"):
            with self.subTest(event=event):
                self.assertEqual(self.policy(runs=[self.completed(minutes=19.9, event=event)])["reason"],
                                 "recent_collecting_run")
                self.assertEqual(self.policy(runs=[self.completed(minutes=20, event=event)])["action"],
                                 "dispatch")
                self.assertEqual(self.policy(runs=[self.completed(minutes=-1, event=event)])["action"],
                                 "skip")

    def test_recent_completed_push_does_not_count_as_collection(self):
        self.assertEqual(self.policy(runs=[self.completed(minutes=1, event="push")])["action"], "dispatch")

    def test_busy_run_is_checked_even_when_after_ten_completed_fixture_rows(self):
        runs = [self.completed(minutes=30)] * 10 + [self.completed(status="queued", event="push")]
        self.assertEqual(self.policy(runs=runs)["reason"], "workflow_run_pending")

    def test_invalid_run_status_event_and_collection_time_fail_closed(self):
        for run in ({"status": None}, {"status": "completed"},
                    self.completed(created_at="bad")):
            with self.subTest(run=run), self.assertRaises(watch.SafeError):
                self.policy(runs=[run])
        self.github.runs.return_value = [self.completed(created_at="bad")]
        with self.assertRaises(watch.SafeError):
            self.run_watch()
        self.github.dispatch.assert_not_called()
        self.assertFalse((self.directory/watch.STATE_FILE).exists())

    def test_inactive_before_end_never_dispatches_or_stops_timer(self):
        for status in ("disabled_manually", "disabled_inactivity", "deleted", "unknown"):
            self.github.workflow.return_value = status
            result = self.run_watch(dry_run=True)
            self.assertEqual(result["action"], "skip")
        self.github.runs.assert_not_called()
        self.github.dispatch.assert_not_called()
        self.timer.assert_not_called()

    def test_disabled_after_end_stops_only_own_timer(self):
        self.github.workflow.return_value = "disabled_manually"
        result = self.run_watch(now=self.stop+timedelta(seconds=1))
        self.assertEqual(result["action"], "timer_stopped")
        self.timer.assert_called_once_with()
        self.github.runs.assert_not_called()
        self.github.dispatch.assert_not_called()

    def test_hard_stop_does_not_depend_on_github_or_state_json(self):
        self.directory.mkdir()
        (self.directory/watch.STATE_FILE).write_text("invalid-state")
        result = self.run_watch(now=self.stop+timedelta(hours=24))
        self.assertEqual(result["reason"], "hard_stop_reached")
        self.timer.assert_called_once_with()
        self.github.workflow.assert_not_called()
        self.github.dispatch.assert_not_called()

    def test_normal_dispatch_records_cooldown_before_api_visibility(self):
        def check_reservation():
            state = watch.read_state(self.directory)
            self.assertEqual(state["last_dispatch_attempt_at"], watch.stamp(self.now))
        self.github.dispatch.side_effect = check_reservation
        result = self.run_watch()
        self.assertEqual(result["action"], "dispatched")
        second = self.run_watch(now=self.now+timedelta(minutes=1))
        self.assertEqual(second["reason"], "recent_local_dispatch_attempt")
        self.assertEqual(self.github.dispatch.call_count, 1)

    def test_final_archive_is_reserved_before_dispatch_and_never_repeated(self):
        final_time = self.stop+timedelta(minutes=21)
        def check_reservation():
            state = watch.read_state(self.directory)
            self.assertEqual(state["final_dispatch_reserved_at"], watch.stamp(final_time))
            raise watch.SafeError("github_request_failed")  # Timeout may have reached GitHub.
        self.github.dispatch.side_effect = check_reservation
        with self.assertRaises(watch.SafeError):
            self.run_watch(now=final_time)
        result = self.run_watch(now=final_time+timedelta(hours=2))
        self.assertEqual(result["reason"], "final_dispatch_already_reserved")
        self.assertEqual(self.github.dispatch.call_count, 1)

    def test_after_stop_busy_or_recent_run_does_not_reserve_final_attempt(self):
        now = self.stop+timedelta(minutes=2)
        for run in (self.completed(status="in_progress"),
                    self.completed(event="workflow_dispatch", created_at=watch.stamp(now-timedelta(minutes=1)))):
            with self.subTest(run=run):
                self.github.runs.return_value = [run]
                self.assertEqual(self.run_watch(now=now)["action"], "skip")
                self.assertFalse((self.directory/watch.STATE_FILE).exists())
        self.github.dispatch.assert_not_called()

    def test_dry_run_dispatch_and_final_dispatch_never_create_files(self):
        for now in (self.now, self.stop+timedelta(minutes=30)):
            result = self.run_watch(now=now, dry_run=True)
            self.assertEqual(result["action"], "would_dispatch")
            self.assertFalse(self.directory.exists())
        self.github.dispatch.assert_not_called()
        self.timer.assert_not_called()

    def test_dry_run_stop_never_creates_files_or_stops_timer(self):
        self.github.workflow.return_value = "disabled_manually"
        for now in (self.stop, self.stop+timedelta(hours=24)):
            self.assertEqual(self.run_watch(now=now, dry_run=True)["action"], "would_stop_timer")
            self.assertFalse(self.directory.exists())
        self.timer.assert_not_called()

    def test_dry_run_existing_state_and_lock_are_unchanged(self):
        self.directory.mkdir()
        (self.directory/watch.LOCK_FILE).write_text("")
        watch.save_state(self.directory, {"schema_version": 1})
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.directory.iterdir()}
        self.run_watch(dry_run=True)
        after = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in self.directory.iterdir()}
        self.assertEqual(before, after)

    def test_flock_prevents_a_second_local_entry(self):
        with watch.local_lock(self.directory, False) as acquired:
            self.assertTrue(acquired)
            result = self.run_watch()
            self.assertEqual(result["reason"], "local_watcher_running")
            result = self.run_watch(dry_run=True)
            self.assertEqual(result["reason"], "local_watcher_running")
        self.github.workflow.assert_not_called()
        self.github.dispatch.assert_not_called()

    def test_api_failure_never_dispatches(self):
        self.github.workflow.side_effect = watch.SafeError("github_auth_failed")
        with self.assertRaises(watch.SafeError):
            self.run_watch()
        self.github.dispatch.assert_not_called()

    def test_invalid_manifest_or_local_state_never_dispatches(self):
        self.manifest.write_text("{}")
        with self.assertRaises(watch.SafeError):
            self.run_watch()
        self.github.workflow.assert_not_called()
        self.github.dispatch.assert_not_called()

    def test_reservation_failure_never_dispatches(self):
        with patch.object(watch, "save_state", side_effect=watch.SafeError("local_reservation_failed")):
            with self.assertRaises(watch.SafeError):
                self.run_watch(now=self.stop+timedelta(minutes=30))
        self.github.dispatch.assert_not_called()

    def test_state_directory_uses_absolute_xdg_or_home(self):
        with patch.dict(os.environ, {"XDG_STATE_HOME": str(self.root)}):
            self.assertEqual(watch.state_directory(), self.root/"nextfest-monitor")
        with patch.dict(os.environ, {"XDG_STATE_HOME": "relative"}), patch.object(Path, "home", return_value=self.root):
            self.assertEqual(watch.state_directory(), self.root/".local/state/nextfest-monitor")


class GitHubAdapterTests(unittest.TestCase):
    def test_token_is_captured_and_only_passed_as_gh_token_environment(self):
        secret = "fake-test-token-not-a-credential"
        calls = []
        outputs = [secret+"\n", '{"state":"active"}', '{"workflow_runs":[]}', ""]
        def runner(args, **kwargs):
            calls.append((args, kwargs))
            return subprocess.CompletedProcess(args, 0, outputs.pop(0), "private stderr")
        client = watch.GitHub(runner=runner)
        output = io.StringIO()
        with patch.dict(os.environ, {"GH_TOKEN": "wrong-account", "GITHUB_TOKEN": "other", "GH_DEBUG": "api"}), redirect_stdout(output):
            self.assertEqual(client.workflow(), "active")
            self.assertEqual(client.runs(), [])
            client.dispatch()
        self.assertEqual(output.getvalue(), "")
        self.assertEqual(calls[0][0], ["gh", "auth", "token", "--hostname", "github.com", "--user", "inh1095"])
        self.assertNotIn("GH_TOKEN", calls[0][1]["env"])
        self.assertNotIn("GITHUB_TOKEN", calls[0][1]["env"])
        for args, kwargs in calls[1:]:
            self.assertEqual(kwargs["env"]["GH_TOKEN"], secret)
            self.assertNotIn("GH_DEBUG", kwargs["env"])
            self.assertNotIn(secret, " ".join(args))
            self.assertNotIn("steam", " ".join(args).lower())
            self.assertTrue(kwargs["capture_output"])
        self.assertIn("repos/inh1095/nextfest-2026/actions/workflows/monitor.yml/runs?per_page=10", calls[2][0])
        self.assertEqual(calls[-1][0][-3:], ["-f", "ref=main", "--silent"])

    def test_auth_and_json_failures_never_expose_child_output(self):
        failures = [subprocess.CompletedProcess([], 1, "secret stdout", "secret stderr"),
                    subprocess.TimeoutExpired(["gh"], 30, output="secret stdout", stderr="secret stderr")]
        for failure in failures:
            runner = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
            with self.subTest(failure=type(failure).__name__), self.assertRaises(watch.SafeError) as caught:
                watch.GitHub(runner).workflow()
            self.assertEqual(str(caught.exception), "github_auth_failed")
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, "fake-token", ""),
                                   subprocess.CompletedProcess([], 0, "not-json secret", "")])
        with self.assertRaises(watch.SafeError) as caught:
            watch.GitHub(runner).workflow()
        self.assertEqual(str(caught.exception), "github_json_invalid")

    def test_api_failure_code_is_safe(self):
        runner = Mock(side_effect=[subprocess.CompletedProcess([], 0, "fake-token", ""),
                                   subprocess.CompletedProcess([], 1, "secret", "secret")])
        with self.assertRaises(watch.SafeError) as caught:
            watch.GitHub(runner).runs()
        self.assertEqual(str(caught.exception), "github_request_failed")

    def test_stop_timer_targets_only_the_named_user_timer(self):
        runner = Mock(return_value=subprocess.CompletedProcess([], 0, "", ""))
        watch.stop_timer(runner)
        self.assertEqual(runner.call_args.args[0], ["systemctl", "--user", "disable", "--now", "nextfest-monitor-watch.timer"])

    def test_main_outputs_only_safe_json_on_failure(self):
        for failure, code in [(watch.SafeError("github_request_failed"), "github_request_failed"),
                              (RuntimeError("secret token in stderr"), "watcher_internal_error")]:
            with patch.object(watch, "run_once", side_effect=failure), redirect_stdout(io.StringIO()) as output:
                result = watch.main(["--dry-run"])
            payload = json.loads(output.getvalue())
            self.assertEqual(result, 1)
            self.assertEqual(payload["reason"], code)
            self.assertNotIn("secret", output.getvalue())


if __name__ == "__main__":
    unittest.main()
