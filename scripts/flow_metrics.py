#!/usr/bin/env python3
"""Record stage times for pull requests and external writes, and publish a daily table."""
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

STAGES = ("opened", "ready", "review", "approve", "merge", "deploy")
CAUSES = ("gate result", "gate or pin rework", "head drift", "serial hold", "owner")
WAIT_LIMIT_MINUTES = 5


def moment(value):
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError("Times need a UTC offset: " + value)
    return stamp.astimezone(timezone.utc)


def events(record):
    """Return the record's events in time order, rejecting unknown stages and causes."""
    result = []
    for event in record["events"]:
        if event["type"] not in STAGES:
            raise ValueError("Unknown stage: " + str(event["type"]))
        if event.get("cause") is not None and event["cause"] not in CAUSES:
            raise ValueError("Unknown wait cause: " + str(event["cause"]))
        result.append({**event, "time": moment(event["at"])})
    return sorted(result, key=lambda event: event["time"])


def waits(record):
    """Return (cause, minutes) for each gap over five minutes; every such gap needs a cause on the event that ends it.

    The gap before a review result is the gate's own machine time, not a wait.
    """
    result = []
    ordered = events(record)
    for before, after in zip(ordered, ordered[1:]):
        minutes = (after["time"] - before["time"]).total_seconds() / 60
        if minutes > WAIT_LIMIT_MINUTES and after["type"] != "review":
            if after.get("cause") is None:
                raise ValueError(f"Untagged wait of {minutes:.0f} minutes before {after['type']} on {record['pr']}")
            result.append((after["cause"], minutes))
    return result


def stage_times(record, stage):
    return [event["time"] for event in events(record) if event["type"] == stage]


def ready_to_merge(record):
    ready, merge = stage_times(record, "ready"), stage_times(record, "merge")
    if not ready or not merge:
        return None
    return (merge[-1] - ready[0]).total_seconds() / 60


def percentile(values, share):
    """Nearest-rank percentile of a non-empty list."""
    ordered = sorted(values)
    return ordered[max(math.ceil(share * len(ordered)) - 1, 0)]


def daily_table(records, day):
    """Summarize the PRs merged on one UTC day (YYYY-MM-DD)."""
    merged = [record for record in records if any(time.date().isoformat() == day for time in stage_times(record, "merge"))]
    minutes = [value for value in map(ready_to_merge, merged) if value is not None]
    by_cause = Counter()
    for record in merged:
        for cause, wait in waits(record):
            by_cause[cause] += wait
    return {
        "day": day, "merged": len(merged),
        "median_minutes": statistics.median(minutes) if minutes else None,
        "p90_minutes": percentile(minutes, 0.9) if minutes else None,
        "repeat_ready": sum(max(len(stage_times(record, "ready")) - 1, 0) for record in merged),
        "wait_minutes_by_cause": {cause: round(by_cause[cause], 1) for cause in CAUSES},
    }


def render(table):
    def number(value):
        return "none" if value is None else f"{value:.1f}"
    lines = [f"Merged on {table['day']}: {table['merged']}",
             f"First /ready to merge: median {number(table['median_minutes'])} min, 90th percentile {number(table['p90_minutes'])} min",
             f"Repeat /ready comments: {table['repeat_ready']}", "Waiting minutes by cause:"]
    lines += [f"  {cause}: {minutes}" for cause, minutes in table["wait_minutes_by_cause"].items()]
    return "\n".join(lines)


def log_write(path, action, target, outcome, started, answered=None):
    """Append one blocked or prompted external write with its wait."""
    if outcome not in ("refused", "prompted"):
        raise ValueError("Outcome must be refused or prompted")
    begin = moment(started)
    end = moment(answered) if answered else begin
    entry = {"action": action, "target": target, "outcome": outcome, "started": begin.isoformat(),
             "answered": end.isoformat(), "wait_seconds": (end - begin).total_seconds()}
    with Path(path).open("a") as handle:
        handle.write(json.dumps(entry) + "\n")
    return entry


def main(argv):
    if argv[:1] == ["table"] and len(argv) == 3:
        print(render(daily_table(json.loads(Path(argv[1]).read_text()), argv[2])))
    elif argv[:1] == ["log-write"] and len(argv) in (6, 7):
        log_write(*argv[1:])
    else:
        raise SystemExit("usage: flow_metrics.py table RECORDS.json DAY | log-write LOG ACTION TARGET OUTCOME STARTED [ANSWERED]")


if __name__ == "__main__":
    main(sys.argv[1:])
