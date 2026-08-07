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
from screenloop import schedule
from screenloop.store import Store
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
