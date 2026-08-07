import datetime as dt
import unittest

from screenloop import schedule


def at(day: str, clock: str) -> dt.datetime:
    """A datetime in the week of 2026-08-03, which is a Monday."""
    index = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"].index(day)
    hour, minute = (int(part) for part in clock.split(":"))
    return dt.datetime(2026, 8, 3 + index, hour, minute)


class ParsingTests(unittest.TestCase):
    def test_time_round_trips(self):
        self.assertEqual(schedule.format_time(schedule.parse_time("08:05")), "08:05")
        self.assertEqual(schedule.parse_time("23:59"), dt.time(23, 59))

    def test_time_rejects_nonsense(self):
        for value in ["", "8", "25:00", "08:60", "aa:bb", "08-05"]:
            with self.subTest(value=value), self.assertRaises(schedule.ScheduleError):
                schedule.parse_time(value)

    def test_days_round_trip(self):
        self.assertEqual(schedule.parse_days("0,1,2,3,4"), schedule.WORKWEEK)
        self.assertEqual(schedule.format_days(schedule.WORKWEEK), "0,1,2,3,4")

    def test_days_none_means_every_day(self):
        self.assertEqual(schedule.parse_days(None), schedule.EVERY_DAY)

    def test_days_empty_string_selects_nothing(self):
        self.assertEqual(schedule.parse_days(""), frozenset())

    def test_days_rejects_out_of_range(self):
        for value in ["7", "-1", "mon"]:
            with self.subTest(value=value), self.assertRaises(schedule.ScheduleError):
                schedule.parse_days(value)

    def test_equal_start_and_end_is_rejected(self):
        with self.assertRaises(schedule.ScheduleError):
            schedule.build_window("0,1,2,3,4", "08:00", "08:00")


class DaytimeWindowTests(unittest.TestCase):
    def setUp(self):
        self.window = schedule.build_window("0,1,2,3,4", "08:00", "20:00")

    def test_open_during_the_working_day(self):
        self.assertTrue(self.window.is_open(at("mon", "08:00")))
        self.assertTrue(self.window.is_open(at("wed", "13:37")))
        self.assertTrue(self.window.is_open(at("fri", "19:59")))

    def test_closed_outside_the_working_day(self):
        self.assertFalse(self.window.is_open(at("mon", "07:59")))
        self.assertFalse(self.window.is_open(at("mon", "20:00")))
        self.assertFalse(self.window.is_open(at("mon", "23:30")))
        self.assertFalse(self.window.is_open(at("tue", "03:00")))

    def test_closed_at_the_weekend(self):
        self.assertFalse(self.window.is_open(at("sat", "13:00")))
        self.assertFalse(self.window.is_open(at("sun", "13:00")))

    def test_next_open_is_the_same_morning_before_it_starts(self):
        self.assertEqual(self.window.next_open_at(at("mon", "06:00")), at("mon", "08:00"))

    def test_next_open_skips_the_weekend(self):
        next_monday = at("mon", "08:00") + dt.timedelta(days=7)
        self.assertEqual(self.window.next_open_at(at("fri", "21:00")), next_monday)

    def test_closes_at_the_end_of_the_same_day(self):
        self.assertEqual(self.window.closes_at(at("wed", "13:00")), at("wed", "20:00"))

    def test_closes_at_is_none_while_closed(self):
        self.assertIsNone(self.window.closes_at(at("sat", "13:00")))


class OvernightWindowTests(unittest.TestCase):
    """A 22:00-06:00 window belongs to the day it opens on."""

    def setUp(self):
        self.window = schedule.build_window("4,5", "22:00", "06:00")

    def test_open_late_on_a_selected_day(self):
        self.assertTrue(self.window.is_open(at("fri", "23:30")))

    def test_still_open_after_midnight(self):
        self.assertTrue(self.window.is_open(at("sat", "05:59")))

    def test_closed_once_the_morning_ends(self):
        self.assertFalse(self.window.is_open(at("sat", "06:00")))

    def test_sunday_morning_belongs_to_saturday_night(self):
        self.assertTrue(self.window.is_open(at("sun", "02:00")))

    def test_monday_morning_does_not(self):
        self.assertFalse(self.window.is_open(at("mon", "02:00")))

    def test_closes_the_next_morning(self):
        self.assertEqual(self.window.closes_at(at("fri", "23:00")), at("sat", "06:00"))

    def test_closes_this_morning_when_past_midnight(self):
        self.assertEqual(self.window.closes_at(at("sat", "01:00")), at("sat", "06:00"))


class EmptyWindowTests(unittest.TestCase):
    def test_a_window_with_no_days_never_opens(self):
        window = schedule.build_window("", "08:00", "20:00")
        self.assertFalse(window.is_open(at("mon", "12:00")))
        self.assertIsNone(window.next_open_at(at("mon", "12:00")))


class AllDayWindowTests(unittest.TestCase):
    def test_full_day_window_covers_almost_everything(self):
        window = schedule.build_window("0,1,2,3,4,5,6", "00:00", "23:59")
        self.assertTrue(window.is_open(at("sun", "12:00")))
        self.assertTrue(window.is_open(at("mon", "00:00")))
        self.assertFalse(window.is_open(at("mon", "23:59")))


class ScheduleInheritanceTests(unittest.TestCase):
    GLOBAL = {"enabled": True, "days": "0", "start": "08:00", "end": "09:00"}

    @staticmethod
    def custom(entity_id: int, start: str, end: str) -> dict:
        return {
            "id": entity_id,
            "schedule_mode": schedule.CUSTOM,
            "schedule_days": "0,1,2,3,4,5,6",
            "schedule_start": start,
            "schedule_end": end,
        }

    def test_nearest_non_inheriting_group_wins(self):
        tv = {
            "id": 10,
            "schedule_mode": schedule.INHERIT,
            "schedule_groups": [
                {"id": 2, "schedule_mode": schedule.INHERIT},
                self.custom(1, "10:00", "18:00"),
            ],
        }

        window = schedule.resolve_window(tv, self.GLOBAL)

        self.assertIsNotNone(window)
        self.assertEqual(schedule.format_time(window.start), "10:00")

    def test_child_group_always_overrides_parent_and_global(self):
        tv = {
            "id": 10,
            "schedule_mode": schedule.INHERIT,
            "schedule_groups": [
                {"id": 2, "schedule_mode": schedule.ALWAYS},
                self.custom(1, "10:00", "18:00"),
            ],
        }

        self.assertIsNone(schedule.resolve_window(tv, self.GLOBAL))

    def test_invalid_group_custom_falls_through_to_parent(self):
        tv = {
            "id": 10,
            "schedule_mode": schedule.INHERIT,
            "schedule_groups": [
                self.custom(2, "bad", "18:00"),
                self.custom(1, "11:00", "17:00"),
            ],
        }

        window = schedule.resolve_window(tv, self.GLOBAL)

        self.assertIsNotNone(window)
        self.assertEqual(schedule.format_time(window.start), "11:00")


if __name__ == "__main__":
    unittest.main()
