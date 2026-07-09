"""Summarize SRDatalog runtime index-eviction logs.

Input lines look like:

    [evict-index] step=49 rel=StackDefUseLiveVarAtBlockEnd_Full ...

The script ranks evicted physical indexes by byte count when present, falling
back to row count for older logs. This is useful for identifying which dead
index layouts are likely to contribute most reusable GPU allocator capacity
before a later pressure point.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO

EVICT_RE = re.compile(
  r"\[evict-index\]\s+"
  r"step=(?P<step>-?\d+)\s+"
  r"rel=(?P<rel>\S+)\s+"
  r"ver=(?P<ver>\S+)\s+"
  r"index=(?P<index>\[[^\]]*\])\s+"
  r"existed=(?P<existed>[01])\s+"
  r"evicted=(?P<evicted>[01])\s+"
  r"index_size=(?P<index_size>\d+)\s+"
  r"(?:index_bytes=(?P<index_bytes>\d+)\s+)?"
  r"relation_size=(?P<relation_size>\d+)"
)


@dataclass(frozen=True)
class Eviction:
  step: int
  rel: str
  version: str
  index: str
  existed: bool
  evicted: bool
  index_size: int
  index_bytes: int
  relation_size: int

  @property
  def index_mib(self) -> float:
    return self.index_bytes / (1024.0 * 1024.0)


def _read_lines(path: str) -> list[str]:
  if path == "-":
    return sys.stdin.readlines()
  return Path(path).read_text(encoding="utf-8").splitlines()


def _parse(lines: list[str]) -> list[Eviction]:
  out: list[Eviction] = []
  for line in lines:
    match = EVICT_RE.search(line)
    if match is None:
      continue
    out.append(
      Eviction(
        step=int(match.group("step")),
        rel=match.group("rel"),
        version=match.group("ver"),
        index=match.group("index"),
        existed=match.group("existed") == "1",
        evicted=match.group("evicted") == "1",
        index_size=int(match.group("index_size")),
        index_bytes=int(match.group("index_bytes") or 0),
        relation_size=int(match.group("relation_size")),
      )
    )
  return out


def _print_table(rows: list[Eviction], out: TextIO) -> None:
  print("step\tindex_size\tindex_bytes\tindex_mib\trelation_size\trel\tver\tindex\tevicted", file=out)
  for row in rows:
    print(
      f"{row.step}\t{row.index_size}\t{row.index_bytes}\t{row.index_mib:.1f}\t"
      f"{row.relation_size}\t"
      f"{row.rel}\t{row.version}\t{row.index}\t{int(row.evicted)}",
      file=out,
    )


def _group_key(row: Eviction, mode: str) -> tuple[str, ...]:
  if mode == "rel":
    return (row.rel,)
  if mode == "rel,index":
    return (row.rel, row.index)
  raise ValueError(f"unsupported --group-by value: {mode}")


def _print_grouped(rows: list[Eviction], mode: str, top: int, out: TextIO) -> None:
  groups: dict[tuple[str, ...], tuple[int, int, int, int, int, int]] = {}
  for row in rows:
    key = _group_key(row, mode)
    total_size, max_size, total_bytes, max_bytes, count, first_step = groups.get(
      key, (0, 0, 0, 0, 0, row.step)
    )
    groups[key] = (
      total_size + row.index_size,
      max(max_size, row.index_size),
      total_bytes + row.index_bytes,
      max(max_bytes, row.index_bytes),
      count + 1,
      min(first_step, row.step),
    )

  ranked = sorted(groups.items(), key=lambda item: (item[1][2], item[1][0]), reverse=True)
  if mode == "rel":
    print(
      "total_index_size\tmax_index_size\ttotal_index_bytes\tmax_index_bytes\t"
      "total_index_mib\tcount\tfirst_step\trel",
      file=out,
    )
    for (rel,), (total, max_size, total_bytes, max_bytes, count, first_step) in ranked[:top]:
      print(
        f"{total}\t{max_size}\t{total_bytes}\t{max_bytes}\t"
        f"{total_bytes / (1024.0 * 1024.0):.1f}\t{count}\t{first_step}\t{rel}",
        file=out,
      )
  else:
    print(
      "total_index_size\tmax_index_size\ttotal_index_bytes\tmax_index_bytes\t"
      "total_index_mib\tcount\tfirst_step\trel\tindex",
      file=out,
    )
    for (
      rel,
      index,
    ), (
      total,
      max_size,
      total_bytes,
      max_bytes,
      count,
      first_step,
    ) in ranked[:top]:
      print(
        f"{total}\t{max_size}\t{total_bytes}\t{max_bytes}\t"
        f"{total_bytes / (1024.0 * 1024.0):.1f}\t{count}\t{first_step}\t{rel}\t{index}",
        file=out,
      )


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("log", nargs="?", default="-", help="Log path, or '-' for stdin.")
  parser.add_argument("--top", type=int, default=20, help="Show this many largest evictions.")
  parser.add_argument(
    "--before-step",
    type=int,
    default=None,
    help="Only include evictions whose generated step is before this step.",
  )
  parser.add_argument(
    "--through-step",
    type=int,
    default=None,
    help="Only include evictions whose generated step is <= this step.",
  )
  parser.add_argument(
    "--min-size",
    type=int,
    default=0,
    help="Only include evictions with index_size at least this value.",
  )
  parser.add_argument(
    "--min-bytes",
    type=int,
    default=0,
    help="Only include evictions with index_bytes at least this value.",
  )
  parser.add_argument(
    "--sort-by",
    choices=("bytes", "rows"),
    default="bytes",
    help="Rank individual evictions by byte count or row count.",
  )
  parser.add_argument(
    "--group-by",
    choices=("rel", "rel,index"),
    default="",
    help="Aggregate evictions by relation or relation+index instead of printing individual rows.",
  )
  args = parser.parse_args()

  rows = _parse(_read_lines(args.log))
  rows = [row for row in rows if row.index_size >= args.min_size]
  rows = [row for row in rows if row.index_bytes >= args.min_bytes]
  if args.before_step is not None:
    rows = [row for row in rows if row.step < args.before_step]
  if args.through_step is not None:
    rows = [row for row in rows if row.step <= args.through_step]

  if args.sort_by == "bytes":
    rows.sort(key=lambda row: (row.index_bytes, row.index_size), reverse=True)
  else:
    rows.sort(key=lambda row: (row.index_size, row.index_bytes), reverse=True)
  if args.group_by:
    _print_grouped(rows, args.group_by, args.top, sys.stdout)
  else:
    _print_table(rows[: args.top], sys.stdout)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
