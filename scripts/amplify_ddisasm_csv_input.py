'''Amplify an interned ddisasm CSV input directory.

The ddisasm benchmark input is already interned: every token is an integer ID,
and `ddisasm_consts.json` identifies IDs that the generated rules compare
against directly. This script creates N independent copies by offsetting every
non-constant ID in copies after the first.
'''

from __future__ import annotations

import argparse
import json
from pathlib import Path


def _load_json(path: Path) -> dict:
  return json.loads(path.read_text())


def _derive_stride(src_dir: Path) -> int:
  max_value = -1
  for csv_path in sorted(src_dir.glob("*.csv")):
    with csv_path.open(encoding="utf-8") as inf:
      for line_no, line in enumerate(inf, start=1):
        line = line.strip()
        if not line:
          continue
        for value in line.split(","):
          try:
            parsed = int(value)
          except ValueError as exc:
            raise ValueError(f"expected integer CSV value in {csv_path}:{line_no}: {value!r}") from exc
          max_value = max(max_value, parsed)
  if max_value < 0:
    raise ValueError(f"could not derive amplification stride from {src_dir}")
  return max_value + 1


def _amplify_value(value: str, copy_idx: int, stride: int, stable_values: set[int]) -> str:
  parsed = int(value)
  if copy_idx == 0 or parsed in stable_values:
    return value
  return str(parsed + copy_idx * stride)


def _amplify_row(line: str, copy_idx: int, stride: int, stable_values: set[int]) -> str:
  return ",".join(
    _amplify_value(value, copy_idx, stride, stable_values)
    for value in line.rstrip("\n").split(",")
  )


def amplify(src_dir: Path, out_dir: Path, copies: int) -> None:
  if copies < 1:
    raise ValueError("--copies must be >= 1")

  consts = _load_json(src_dir / "ddisasm_consts.json")
  stats_path = src_dir / "intern_stats.json"
  if stats_path.exists():
    stats = _load_json(stats_path)
    stride = int(stats["unique_tokens"])
    stride_source = str(stats_path)
  else:
    stats = {}
    stride = _derive_stride(src_dir)
    stride_source = "derived from CSV max_id + 1"
  stable_values = {int(value) for value in consts.values()}

  out_dir.mkdir(parents=True, exist_ok=True)

  row_counts: dict[str, int] = {}
  for src in sorted(src_dir.glob("*.csv")):
    dst = out_dir / src.name
    rows = 0
    with src.open() as inf, dst.open("w") as outf:
      for line in inf:
        if not line.strip():
          continue
        for copy_idx in range(copies):
          outf.write(_amplify_row(line, copy_idx, stride, stable_values))
          outf.write("\n")
          rows += 1
    row_counts[src.name] = rows
    print(f"{src.name}: {rows} rows")

  (out_dir / "ddisasm_consts.json").write_text(json.dumps(consts, indent=2) + "\n")
  (out_dir / "intern_stats.json").write_text(
    json.dumps(
      {
        "amplified_from": str(src_dir),
        "copies": copies,
        "offset_stride": stride,
        "offset_stride_source": stride_source,
        "stable_values": sorted(stable_values),
        "unique_tokens_estimate": len(stable_values)
        + (stride - len(stable_values)) * copies,
        "row_counts": row_counts,
      },
      indent=2,
      sort_keys=True,
    )
    + "\n"
  )


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("src_dir", type=Path)
  parser.add_argument("out_dir", type=Path)
  parser.add_argument("--copies", type=int, required=True)
  args = parser.parse_args()

  amplify(args.src_dir, args.out_dir, args.copies)
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
