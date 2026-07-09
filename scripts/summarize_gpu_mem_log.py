'''Summarize SRDATALOG_GPU_MEM_LOG output.

Prints the largest positive memory jumps between consecutive `[gpu-mem]`
records. This is intended for detailed generated-runner logs, where recursive
steps can emit thousands of checkpoints.
'''

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

MEM_RE = re.compile(r"^\[gpu-mem\] label=(?P<label>.*?) used_mib=(?P<used>\d+) ")
FIELD_RE_TEMPLATE = r"(?:^|\s){name}=(?P<value>-?\d+)(?:\s|$)"


@dataclass(frozen=True)
class Event:
  line_no: int
  label: str
  used_mib: int
  rmm_current_bytes: int | None = None
  rmm_current_mib: int | None = None
  rmm_peak_bytes: int | None = None
  rmm_peak_mib: int | None = None
  rmm_pool_bytes: int | None = None
  rmm_pool_mib: int | None = None


def _int_field(line: str, name: str) -> int | None:
  match = re.search(FIELD_RE_TEMPLATE.format(name=re.escape(name)), line)
  if match is None:
    return None
  return int(match.group("value"))


def _events(path: Path) -> list[Event]:
  events: list[Event] = []
  with path.open(encoding="utf-8", errors="replace") as f:
    for line_no, line in enumerate(f, start=1):
      match = MEM_RE.match(line)
      if match:
        events.append(
          Event(
            line_no=line_no,
            label=match.group("label"),
            used_mib=int(match.group("used")),
            rmm_current_bytes=_int_field(line, "rmm_current_bytes"),
            rmm_current_mib=_int_field(line, "rmm_current_mib"),
            rmm_peak_bytes=_int_field(line, "rmm_peak_bytes"),
            rmm_peak_mib=_int_field(line, "rmm_peak_mib"),
            rmm_pool_bytes=_int_field(line, "rmm_pool_bytes"),
            rmm_pool_mib=_int_field(line, "rmm_pool_mib"),
          )
        )
  return events


def _metric(event: Event, name: str) -> int | None:
  if name == "used_mib":
    return event.used_mib
  return getattr(event, name)


def _print_jumps(events: list[Event], metric: str, top: int, min_delta: int) -> None:
  jumps: list[tuple[int, Event, Event, int, int]] = []
  prev = events[0]
  for event in events[1:]:
    before_value = _metric(prev, metric)
    after_value = _metric(event, metric)
    if before_value is not None and after_value is not None:
      delta = after_value - before_value
      if delta >= min_delta:
        jumps.append((delta, prev, event, before_value, after_value))
    prev = event

  jumps.sort(key=lambda item: item[0], reverse=True)
  print(f"largest positive {metric} jumps:")
  for delta, before, after, before_value, after_value in jumps[:top]:
    print(
      f"+{delta:>6} MiB  line {after.line_no:<6} "
      f"{before_value:>6}->{after_value:<6}  "
      f"{before.label}  =>  {after.label}"
    )


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("log", type=Path)
  parser.add_argument("--top", type=int, default=25)
  parser.add_argument("--min-delta", type=int, default=1)
  args = parser.parse_args()

  events = _events(args.log)
  if not events:
    print("no [gpu-mem] records found")
    return 1

  print(f"events={len(events)}")
  rmm_events = [event for event in events if event.rmm_current_mib is not None]
  if rmm_events:
    peak_current_bytes = max(event.rmm_current_bytes or 0 for event in rmm_events)
    peak_current = max(event.rmm_current_mib or 0 for event in rmm_events)
    peak_recorded_bytes = max(event.rmm_peak_bytes or 0 for event in rmm_events)
    peak_recorded = max(event.rmm_peak_mib or 0 for event in rmm_events)
    peak_pool_bytes = max(event.rmm_pool_bytes or 0 for event in rmm_events)
    peak_pool = max(event.rmm_pool_mib or 0 for event in rmm_events)
    print(
      "rmm="
      f"events:{len(rmm_events)} "
      f"peak_current_bytes:{peak_current_bytes} "
      f"peak_current_mib:{peak_current} "
      f"peak_recorded_bytes:{peak_recorded_bytes} "
      f"peak_recorded_mib:{peak_recorded} "
      f"peak_pool_bytes:{peak_pool_bytes} "
      f"peak_pool_mib:{peak_pool}"
    )
  _print_jumps(events, "used_mib", args.top, args.min_delta)
  if rmm_events:
    _print_jumps(events, "rmm_current_mib", args.top, args.min_delta)
    _print_jumps(events, "rmm_pool_mib", args.top, args.min_delta)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
