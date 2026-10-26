import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from flow_metrics import daily_table, log_write, ready_to_merge, render, waits


def record(pr, *events):
    return {"pr": pr, "events": [{"type": kind, "at": at, **({"cause": cause[0]} if cause else {})} for kind, at, *cause in events]}


QUICK = record("one", ("opened", "2026-10-25T10:00:00Z"), ("ready", "2026-10-25T10:02:00Z"), ("review", "2026-10-25T10:08:00Z"),
               ("approve", "2026-10-25T10:10:00Z"), ("merge", "2026-10-25T10:12:00Z"))
SLOW = record("two", ("opened", "2026-10-25T10:00:00Z"), ("ready", "2026-10-25T10:01:00Z"), ("ready", "2026-10-25T11:01:00Z", "head drift"),
              ("merge", "2026-10-25T13:01:00Z", "owner"))
OTHER_DAY = record("three", ("ready", "2026-10-24T10:00:00Z"), ("merge", "2026-10-24T10:10:00Z"))


class FlowMetricsTests(unittest.TestCase):
    def test_ready_to_merge_runs_from_the_first_ready(self):
        self.assertEqual(ready_to_merge(QUICK), 10)
        self.assertEqual(ready_to_merge(SLOW), 180)

    def test_a_wait_over_five_minutes_needs_one_listed_cause(self):
        self.assertEqual(waits(QUICK), [])
        self.assertEqual(waits(SLOW), [("head drift", 60), ("owner", 120)])
        with self.assertRaisesRegex(ValueError, "Untagged wait"):
            waits(record("x", ("ready", "2026-10-25T10:00:00Z"), ("merge", "2026-10-25T10:06:00Z")))
        with self.assertRaisesRegex(ValueError, "Unknown wait cause"):
            waits(record("x", ("ready", "2026-10-25T10:00:00Z"), ("merge", "2026-10-25T10:06:00Z", "bad luck")))

    def test_unknown_stage_and_naive_time_are_rejected(self):
        with self.assertRaises(ValueError):
            waits(record("x", ("lunch", "2026-10-25T10:00:00Z")))
        with self.assertRaises(ValueError):
            waits(record("x", ("ready", "2026-10-25T10:00:00")))

    def test_daily_table_counts_only_prs_merged_that_day(self):
        table = daily_table([QUICK, SLOW, OTHER_DAY], "2026-10-25")
        self.assertEqual(table["merged"], 2)
        self.assertEqual(table["median_minutes"], 95)
        self.assertEqual(table["p90_minutes"], 180)
        self.assertEqual(table["repeat_ready"], 1)
        self.assertEqual(table["wait_minutes_by_cause"]["owner"], 120)
        self.assertEqual(table["wait_minutes_by_cause"]["serial hold"], 0)
        self.assertIn("median 95.0 min", render(table))
        self.assertEqual(daily_table([], "2026-10-25")["median_minutes"], None)

    def test_external_write_log_records_the_wait(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "writes.jsonl"
            log_write(path, "push", "ejmlabs/x@" + "a" * 40, "prompted", "2026-10-25T10:00:00Z", "2026-10-25T10:03:30Z")
            log_write(path, "merge", "ejmlabs/x#1", "refused", "2026-10-25T10:05:00Z")
            first, second = map(json.loads, path.read_text().splitlines())
        self.assertEqual((first["outcome"], first["wait_seconds"]), ("prompted", 210))
        self.assertEqual((second["outcome"], second["wait_seconds"]), ("refused", 0))
        with self.assertRaises(ValueError):
            log_write(path, "push", "x", "allowed", "2026-10-25T10:00:00Z")


if __name__ == "__main__":
    unittest.main()
