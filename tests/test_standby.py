"""Regression tests for the loop that kept switching screens back on.

Two TVs were destroyed by running around the clock before this existed. Every
test here asserts an absence -- that nothing was queued, that no push went out.
"""

import datetime as dt
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from screenloop import config as config_module
from screenloop import lifecycle, schedule
from screenloop import worker as worker_module
from screenloop.store import Store
from screenloop.transcode import output_path
from screenloop.worker import Worker


def monday(clock: str) -> dt.datetime:
    hour, minute = (int(part) for part in clock.split(":"))
    return dt.datetime(2026, 8, 3, hour, minute)


class StandbyTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self.store = Store(root / "test.sqlite3")
        source = root / "video.mp4"
        source.write_bytes(b"video")
        self.media_id = self.store.add_media("clip", source, "clip.mp4", source.stat().st_size, "a", duration_seconds=30)
        playlist_id = self.store.create_playlist("playlist")
        self.store.add_playlist_item(playlist_id, self.media_id)
        self.tv_id = self.store.add_tv("TV", "192.168.1.90", "samsung_tizen")
        self.store.update_tv_config(self.tv_id, "TV", "192.168.1.90", "samsung_tizen", playlist_id, True)
        self.store.set_tv_playback_position(self.tv_id, 0, self.media_id)
        self.worker = Worker(self.store)

    def tv(self) -> dict:
        return self.store.list_tvs()[0]

    def at(self, moment: dt.datetime):
        return mock.patch.object(schedule, "now", return_value=moment)


class ManualPowerOffTests(StandbyTestCase):
    def test_renderer_reset_suspends_playback_after_repeated_polls(self):
        """NO_MEDIA_PRESENT is how a Samsung reports that it went to standby."""
        for _ in range(config_module.MANUAL_OFF_CONFIRMATIONS - 1):
            self.worker.note_renderer_state(self.tv(), "NO_MEDIA_PRESENT")
            self.assertIsNone(self.tv()["playback_suspended_at"], "suspended too eagerly")

        self.worker.note_renderer_state(self.tv(), "NO_MEDIA_PRESENT")
        self.assertIsNotNone(self.tv()["playback_suspended_at"])
        self.assertEqual(self.tv()["playback_suspended_reason"], "renderer_reset")

    def test_a_single_reading_is_not_enough(self):
        """TVs report NO_MEDIA_PRESENT briefly while loading the next item."""
        self.worker.note_renderer_state(self.tv(), "NO_MEDIA_PRESENT")
        self.worker.note_renderer_state(self.tv(), "PLAYING")
        for _ in range(config_module.MANUAL_OFF_CONFIRMATIONS - 1):
            self.worker.note_renderer_state(self.tv(), "NO_MEDIA_PRESENT")
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_a_suspended_tv_is_never_pushed(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        self.assertFalse(self.worker.may_push(self.tv()))

    def test_a_suspended_tv_does_not_autoplay(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        self.assertFalse(self.worker.apply_schedule(self.tv()))

    def test_push_next_refuses_a_suspended_tv(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        with mock.patch.object(self.worker, "_push_next_locked") as push:
            self.worker.push_next(self.tv())
        push.assert_not_called()

    def test_the_panel_can_still_force_a_push(self):
        """An operator can see the screen; the heuristics cannot."""
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        with mock.patch.object(self.worker, "_push_next_locked") as push:
            self.worker.push_next(self.tv(), force=True)
        push.assert_called_once()

    def test_a_manual_command_clears_the_suspension(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        self.store.enqueue_command(self.tv_id, "play_next", '{"manual": true}')
        command = self.store.next_pending_command()
        with mock.patch.object(self.worker, "push_next"):
            self.worker.execute_command(command)
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_an_automatic_command_does_not(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        self.store.enqueue_command(self.tv_id, "play_next")
        command = self.store.next_pending_command()
        with mock.patch.object(self.worker, "_push_next_locked") as push:
            self.worker.execute_command(command)
        push.assert_not_called()
        self.assertIsNotNone(self.tv()["playback_suspended_at"])

    def test_rediscovery_does_not_restart_a_suspended_tv(self):
        """Waking briefly from standby used to be read as "the TV came back"."""
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        with mock.patch.object(self.worker, "ensure_control_url", return_value="http://tv/ctl"):
            self.worker.try_recover_tv(self.tv())
        self.assertIsNone(self.store.next_pending_command())


class ManualStopTests(StandbyTestCase):
    """Stop has to mean stopped."""

    def execute(self, action: str, payload: str | None = None):
        self.store.enqueue_command(self.tv_id, action, payload)
        command = self.store.next_pending_command()
        with mock.patch.object(self.worker, "stop_tv"), mock.patch.object(self.worker, "_push_next_locked"):
            self.worker.execute_command(command)
        # next_pending_command returns the oldest queued command, so each one
        # has to be retired before the next call sees anything new.
        self.store.mark_command_done(command["id"])

    def test_stop_suspends_autoplay(self):
        self.execute("stop")

        self.assertIsNotNone(self.tv()["playback_suspended_at"])
        self.assertEqual(self.tv()["playback_suspended_reason"], "stopped_by_operator")

    def test_a_stopped_screen_does_not_restart_once_the_clip_would_have_ended(self):
        """The exact regression: STOPPED plus elapsed duration queued the next item."""
        self.execute("stop")
        tv = self.tv()
        tv["playback_started_at"] = int(time.time()) - 600  # long past the 30s clip

        self.assertFalse(self.worker.apply_schedule(tv))
        self.assertFalse(self.worker.may_push(tv))
        with mock.patch.object(self.worker, "_push_next_locked") as push:
            self.worker.push_next(tv)
        push.assert_not_called()

    def test_the_panel_can_start_it_again(self):
        self.execute("stop")
        self.assertIsNotNone(self.tv()["playback_suspended_at"])

        self.execute("play_next", '{"manual": true}')

        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_restart_playlist_also_clears_it(self):
        self.execute("stop")
        self.execute("restart_playlist", '{"manual": true}')
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_an_automatic_play_next_does_not_clear_it(self):
        self.execute("stop")
        self.execute("play_next")
        self.assertIsNotNone(self.tv()["playback_suspended_at"])


class SuspensionReasonTests(StandbyTestCase):
    """A blackout by schedule must not masquerade as somebody pressing stop."""

    def run_stop(self, payload=None):
        self.store.enqueue_command(self.tv_id, "stop", payload)
        command = self.store.next_pending_command()
        with mock.patch.object(self.worker, "stop_tv"):
            self.worker.execute_command(command)
        self.store.mark_command_done(command["id"])

    def test_an_operator_stop_is_recorded_as_such(self):
        self.run_stop()
        self.assertEqual(self.tv()["playback_suspended_reason"], "stopped_by_operator")

    def test_a_scheduled_stop_leaves_no_suspension(self):
        """The window gate already refuses to push; a suspension would only
        have to be cleared again, and one that is not is how a screen stays
        dark after its window reopens."""
        self.run_stop('{"source": "schedule"}')
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_closing_the_window_tags_the_stop_it_queues(self):
        self.store.set_playback_schedule(True, "0,1,2,3,4", "08:00", "20:00")
        self.store.update_tv_status(self.tv_id, True, "PLAYING")
        with mock.patch.object(schedule, "now", return_value=monday("23:00")):
            self.worker.apply_schedule(self.tv())

        command = self.store.next_pending_command()

        self.assertEqual(command["command"], "stop")
        self.assertTrue(self.worker.command_is_schedule(command))

    def test_an_unparseable_payload_is_not_treated_as_scheduled(self):
        self.assertFalse(self.worker.command_is_schedule({"payload_json": "not json"}))
        self.assertFalse(self.worker.command_is_schedule({"payload_json": None}))


class LifecycleTests(StandbyTestCase):
    """A clip nobody approved must never reach a screen.

    Same shape as the standby guards above: every test asserts an absence, so
    the way to check they still mean something is to remove the lifecycle
    check in `Worker.is_item_playable` and watch them fail.
    """

    def setUp(self):
        super().setUp()
        self.make_ready(self.media_id)

    def make_ready(self, media_id):
        """Transcoded and ready, so the only thing that can stop this clip is
        its lifecycle. Without it the tests would pass for the wrong reason."""
        self.store.ensure_transcode_job(media_id, "samsung_tizen")
        job = next(j for j in self.store.list_transcode_jobs() if j["media_id"] == media_id)
        media = self.store.get_media(media_id)
        self.store.mark_job_done(
            job["id"],
            media_id,
            output_path(Path(media["original_path"]), "samsung_tizen", silent=False, compressed=False),
        )

    def push(self):
        """A push a person asked for: `force` skips the standby and window
        gates, so anything left is the lifecycle refusing."""
        with (
            mock.patch.object(worker_module, "push_video", return_value=False) as push_video,
            mock.patch.object(self.worker, "ensure_control_url", return_value="http://tv/ctl"),
        ):
            self.worker.push_next(self.tv(), force=True)
        return push_video

    def set_lifecycle(self, state):
        self.store.set_media_lifecycle(self.media_id, state)

    def test_a_published_clip_is_pushed(self):
        """The control: without it every absence below could be an accident."""
        self.set_lifecycle(lifecycle.PUBLISHED)

        self.assertEqual(self.push().call_count, 1)

    def test_a_draft_is_never_pushed(self):
        self.set_lifecycle(lifecycle.DRAFT)

        self.push().assert_not_called()

    def test_an_archived_clip_is_never_pushed(self):
        self.set_lifecycle(lifecycle.ARCHIVED)

        self.push().assert_not_called()

    def test_an_expired_clip_is_never_pushed(self):
        self.set_lifecycle(lifecycle.PUBLISHED)
        self.store.set_media_expiry(self.media_id, int(time.time()) - 60)

        self.push().assert_not_called()

    def test_an_expiry_still_ahead_changes_nothing(self):
        self.set_lifecycle(lifecycle.PUBLISHED)
        self.store.set_media_expiry(self.media_id, int(time.time()) + 3600)

        self.assertEqual(self.push().call_count, 1)

    def test_a_clip_whose_window_has_not_opened_is_never_pushed(self):
        """Approving a campaign a week early must not air it a week early."""
        self.set_lifecycle(lifecycle.PUBLISHED)
        self.store.set_media_start(self.media_id, int(time.time()) + 3600)

        self.push().assert_not_called()

    def test_a_start_already_passed_changes_nothing(self):
        self.set_lifecycle(lifecycle.PUBLISHED)
        self.store.set_media_start(self.media_id, int(time.time()) - 60)

        self.assertEqual(self.push().call_count, 1)

    def test_a_clip_waiting_for_its_window_is_not_preloaded_either(self):
        """The preload path hands a TV a clip to play unattended, so a campaign
        that has not started could otherwise slip onto a screen by itself."""
        self.set_lifecycle(lifecycle.PUBLISHED)
        source = Path(self._tmp.name) / "campaign.mp4"
        source.write_bytes(b"video")
        second = self.store.add_media("campaign", source, "campaign.mp4", 5, "b", duration_seconds=30)
        self.make_ready(second)
        playlist_id = int(self.tv()["active_playlist_id"])
        self.store.add_playlist_item(playlist_id, second)
        items = self.store.playlist_items(playlist_id)
        self.assertIsNotNone(self.worker.next_preload_item(self.tv(), items, 0, "samsung_tizen"))

        self.store.set_media_start(second, int(time.time()) + 3600)

        self.assertIsNone(self.worker.next_preload_item(self.tv(), items, 0, "samsung_tizen"))

    def test_a_draft_is_not_preloaded_behind_the_current_clip(self):
        """SetNextAVTransportURI hands the TV a clip to play unattended."""
        self.set_lifecycle(lifecycle.PUBLISHED)
        source = Path(self._tmp.name) / "second.mp4"
        source.write_bytes(b"video")
        second = self.store.add_media("draft", source, "second.mp4", 5, "b", duration_seconds=30)
        self.make_ready(second)
        playlist_id = int(self.tv()["active_playlist_id"])
        self.store.add_playlist_item(playlist_id, second)
        items = self.store.playlist_items(playlist_id)
        self.assertIsNotNone(self.worker.next_preload_item(self.tv(), items, 0, "samsung_tizen"))

        self.store.set_media_lifecycle(second, lifecycle.DRAFT)

        self.assertIsNone(self.worker.next_preload_item(self.tv(), items, 0, "samsung_tizen"))


class EventRetentionTests(StandbyTestCase):
    """Playback telemetry must not evict the records used to diagnose a dark screen."""

    def test_telemetry_cannot_crowd_out_operational_events(self):
        """Enough chatter to have exhausted the shared budget on its own."""
        self.store.add_event(self.tv_id, "playback_suspended", "held")
        for index in range(self.store.EVENT_RETENTION + 100):
            self.store.add_event(self.tv_id, "preload_next_uri", f"chatter {index}")

        kept = {e["message"] for e in self.store.list_events(None, "playback_suspended", 10)}

        self.assertIn("held", kept)

    def test_telemetry_still_trims_itself(self):
        for index in range(self.store.TELEMETRY_EVENT_RETENTION + 40):
            self.store.add_event(self.tv_id, "preload_next_uri", f"chatter {index}")

        rows = self.store.rows("SELECT COUNT(*) n FROM events WHERE event_type = 'preload_next_uri'")

        self.assertLessEqual(int(rows[0]["n"]), self.store.TELEMETRY_EVENT_RETENTION)

    def test_security_events_keep_their_own_budget(self):
        self.store.add_event(None, "login_success", "someone signed in")
        for index in range(self.store.TELEMETRY_EVENT_RETENTION + 20):
            self.store.add_event(self.tv_id, "push_media", f"chatter {index}")

        kept = {e["message"] for e in self.store.list_events(None, "login_success", 10)}

        self.assertIn("someone signed in", kept)


class ScheduleGateTests(StandbyTestCase):
    def enable_window(self, start="08:00", end="20:00", days="0,1,2,3,4"):
        self.store.set_playback_schedule(True, days, start, end)

    def stop_commands(self) -> int:
        return len(self.store.rows("SELECT id FROM tv_commands WHERE command = 'stop'"))

    def test_no_schedule_means_no_restriction(self):
        self.assertTrue(self.worker.may_push(self.tv()))

    def test_pushing_is_allowed_inside_the_window(self):
        self.enable_window()
        with self.at(monday("12:00")):
            self.assertTrue(self.worker.may_push(self.tv()))

    def test_pushing_is_refused_outside_the_window(self):
        self.enable_window()
        with self.at(monday("23:00")):
            self.assertFalse(self.worker.may_push(self.tv()))

    def test_push_next_refuses_outside_the_window(self):
        self.enable_window()
        with self.at(monday("23:00")), mock.patch.object(self.worker, "_push_next_locked") as push:
            self.worker.push_next(self.tv())
        push.assert_not_called()

    def test_closing_the_window_stops_the_screen_once(self):
        self.enable_window()
        self.store.update_tv_status(self.tv_id, True, "PLAYING")
        with self.at(monday("23:00")):
            self.assertFalse(self.worker.apply_schedule(self.tv()))
        command = self.store.next_pending_command()
        self.assertIsNotNone(command)
        self.assertEqual(command["command"], "stop")

        # Still pending, so a second pass must not pile on another stop.
        with self.at(monday("23:00")):
            self.worker.apply_schedule(self.tv())
        self.assertEqual(self.stop_commands(), 1)

    def test_a_stopped_screen_is_not_stopped_again(self):
        self.enable_window()
        self.store.update_tv_status(self.tv_id, True, "STOPPED")
        with self.at(monday("23:00")):
            self.worker.apply_schedule(self.tv())
        self.assertIsNone(self.store.next_pending_command())

    def test_a_tv_can_opt_out_of_the_site_schedule(self):
        self.enable_window()
        self.store.update_tv_schedule(self.tv_id, schedule.ALWAYS, None, None, None)
        with self.at(monday("23:00")):
            self.assertTrue(self.worker.may_push(self.tv()))

    def test_a_tv_can_override_the_site_schedule(self):
        self.enable_window(start="08:00", end="20:00")
        self.store.update_tv_schedule(self.tv_id, schedule.CUSTOM, "0,1,2,3,4", "08:00", "23:00")
        with self.at(monday("22:00")):
            self.assertTrue(self.worker.may_push(self.tv()))
        with self.at(monday("23:30")):
            self.assertFalse(self.worker.may_push(self.tv()))

    def test_worker_uses_group_ancestry_after_a_group_move(self):
        parent = self.store.create_group(
            "Office hours",
            schedule_values=(schedule.CUSTOM, "0,1,2,3,4", "08:00", "20:00"),
        )
        child = self.store.create_group("Lobby", parent)
        always = self.store.create_group(
            "Around the clock",
            schedule_values=(schedule.ALWAYS, None, None, None),
        )
        self.store.set_tv_group(self.tv_id, child)
        self.store.update_tv_status(self.tv_id, True, "PLAYING")

        with self.at(monday("23:00")):
            self.assertFalse(self.worker.apply_schedule(self.store.get_tv(self.tv_id)))
        self.assertEqual(self.store.next_pending_command()["command"], "stop")

        self.store.update_group(child, None, always, True)
        with self.at(monday("23:00")), mock.patch.object(self.worker, "stop_tv") as stop:
            self.worker.process_tv_command()
            self.assertTrue(self.worker.apply_schedule(self.store.get_tv(self.tv_id)))
        stop.assert_not_called()
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_schedule_stop_does_not_become_an_operator_suspension(self):
        self.enable_window()
        self.store.update_tv_status(self.tv_id, True, "PLAYING")
        with self.at(monday("23:00")):
            self.worker.apply_schedule(self.tv())

        with self.at(monday("23:00")), mock.patch.object(self.worker, "stop_tv") as stop:
            self.worker.process_tv_command()

        stop.assert_called_once()
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_an_unusable_custom_schedule_falls_back_to_the_site_one(self):
        """Never fail open: unrestricted is the setting that burns panels."""
        self.enable_window()
        self.store.update_tv_schedule(self.tv_id, schedule.CUSTOM, "0,1,2,3,4", "not-a-time", "20:00")
        with self.at(monday("23:00")):
            self.assertFalse(self.worker.may_push(self.tv()))


class SuspensionExpiryTests(StandbyTestCase):
    def test_a_new_window_clears_a_suspension_from_the_night_before(self):
        self.store.set_playback_schedule(True, "0,1,2,3,4", "08:00", "20:00")
        suspended = monday("09:00") - dt.timedelta(days=3)
        with mock.patch.object(time, "time", return_value=suspended.timestamp()):
            self.store.suspend_tv_playback(self.tv_id, "renderer_reset")

        with self.at(monday("09:00")):
            self.assertTrue(self.worker.apply_schedule(self.tv()))
        self.assertIsNone(self.tv()["playback_suspended_at"])

    def test_a_suspension_inside_the_current_window_survives(self):
        self.store.set_playback_schedule(True, "0,1,2,3,4", "08:00", "20:00")
        suspended = monday("09:00")
        with mock.patch.object(time, "time", return_value=suspended.timestamp()):
            self.store.suspend_tv_playback(self.tv_id, "renderer_reset")

        with self.at(monday("11:00")):
            self.assertFalse(self.worker.apply_schedule(self.tv()))
        self.assertIsNotNone(self.tv()["playback_suspended_at"])

    def test_without_a_schedule_only_a_person_clears_a_suspension(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        self.assertFalse(self.worker.apply_schedule(self.tv()))
        self.assertTrue(self.store.resume_tv_playback(self.tv_id))
        self.assertTrue(self.worker.apply_schedule(self.tv()))


class ScheduleStoreTests(StandbyTestCase):
    def test_the_schedule_is_off_by_default(self):
        """An upgrade must not start blanking screens nobody asked about."""
        self.assertFalse(self.store.get_playback_schedule()["enabled"])

    def test_the_schedule_round_trips(self):
        self.store.set_playback_schedule(True, "5,6", "10:00", "18:30")
        self.assertEqual(
            self.store.get_playback_schedule(),
            {"enabled": True, "days": "5,6", "start": "10:00", "end": "18:30"},
        )

    def test_tvs_default_to_inheriting_the_site_schedule(self):
        self.assertEqual(self.tv()["schedule_mode"], schedule.INHERIT)

    def test_resume_reports_whether_there_was_anything_to_clear(self):
        self.assertFalse(self.store.resume_tv_playback(self.tv_id))
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        self.assertTrue(self.store.resume_tv_playback(self.tv_id))

    def test_suspending_twice_keeps_the_first_timestamp(self):
        self.store.suspend_tv_playback(self.tv_id, "renderer_reset")
        first = self.tv()["playback_suspended_at"]
        self.store.suspend_tv_playback(self.tv_id, "something_else")
        self.assertEqual(self.tv()["playback_suspended_at"], first)
        self.assertEqual(self.tv()["playback_suspended_reason"], "renderer_reset")


if __name__ == "__main__":
    unittest.main()
