'''Convert ddisasm `.facts` trees into this repo's integer CSV input layout.

The translated `examples/ddisasm.py` benchmark expects already-interned integer
CSV files with specific names. Some larger ddisasm datasets are stored as
tab-delimited `.facts` files with string/hex tokens. This script interns every
token consistently, projects `arch.memory_access.facts` down to the 6 columns
used by this benchmark, and writes the expected CSV files plus
`ddisasm_consts.json`.
'''

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

REQUIRED: dict[str, tuple[str, tuple[int, ...] | None]] = {
  "Arch_memory_access_truncate.csv": ("arch.memory_access.facts", (0, 1, 4, 5, 6, 8)),
  "Arch_reg_reg_arithmetic_operation.csv": ("arch.reg_reg_arithmetic_operation.facts", None),
  "Arch_return_reg.csv": ("arch.return_reg.facts", None),
  "Block_next.csv": ("block_next.facts", None),
  "Block_last_instruction.csv": ("block_last_instruction.facts", None),
  "Code_in_block.csv": ("code_in_block.facts", None),
  "Direct_call.csv": ("direct_call.facts", None),
  "May_fallthrough.csv": ("may_fallthrough.facts", None),
  "Reg_def_use_block_last_def.csv": ("reg_def_use.block_last_def.facts", None),
  "Reg_def_use_defined_in_block.csv": ("reg_def_use.defined_in_block.facts", None),
  "Reg_def_use_flow_def.csv": ("reg_def_use.flow_def.facts", None),
  "Reg_def_use_live_var_def.csv": ("reg_def_use.live_var_def.facts", None),
  "Reg_def_use_ref_in_block.csv": ("reg_def_use.ref_in_block.facts", None),
  "Reg_def_use_return_block_end.csv": ("reg_def_use.return_block_end.facts", None),
  "Reg_def_use_used.csv": ("reg_def_use.used.facts", None),
  "Reg_def_use_used_in_block.csv": ("reg_def_use.used_in_block.facts", None),
  "Reg_used_for.csv": ("reg_used_for.facts", None),
  "Relative_jump_table_entry_candidate.csv": ("relative_jump_table_entry_candidate.facts", None),
  "Stack_def_use_def.csv": ("stack_def_use.def.facts", None),
  "Stack_def_use_defined_in_block.csv": ("stack_def_use.defined_in_block.facts", None),
  "Stack_def_use_live_var_def.csv": ("stack_def_use.live_var_def.facts", None),
  "Stack_def_use_ref_in_block.csv": ("stack_def_use.ref_in_block.facts", None),
  "Stack_def_use_used_in_block.csv": ("stack_def_use.used_in_block.facts", None),
  "Stack_def_use_used.csv": ("stack_def_use.used.facts", None),
  "Stack_def_use_live_var_used.csv": ("stack_def_use.live_var_used.facts", None),
  "Jump_table_start.csv": ("jump_table_start.facts", None),
  "Def_used_for_address.csv": ("def_used_for_address.facts", None),
  "Stack_def_use_block_last_def.csv": ("stack_def_use.block_last_def.facts", None),
}

CONST_KEYS = ("LOAD", "STORE", "NONE", "PCRelative")


def _project(fields: list[str], cols: tuple[int, ...] | None, src: Path, line_no: int) -> list[str]:
  if cols is None:
    return fields
  if len(fields) <= max(cols):
    raise ValueError(f"{src}:{line_no}: expected at least {max(cols) + 1} columns, got {len(fields)}")
  return [fields[i] for i in cols]


def _intern_all(tokens: Iterable[str], ids: dict[str, int]) -> list[str]:
  out: list[str] = []
  for token in tokens:
    value = ids.get(token)
    if value is None:
      value = len(ids)
      ids[token] = value
    out.append(str(value))
  return out


def convert(src_dir: Path, out_dir: Path) -> dict[str, int]:
  out_dir.mkdir(parents=True, exist_ok=True)
  ids: dict[str, int] = {}
  row_counts: dict[str, int] = {}

  for out_name, (src_name, cols) in REQUIRED.items():
    src = src_dir / src_name
    if not src.exists():
      raise FileNotFoundError(f"missing required facts file: {src}")
    dst = out_dir / out_name
    rows = 0
    with src.open() as inf, dst.open("w") as outf:
      for line_no, line in enumerate(inf, start=1):
        line = line.rstrip("\n")
        if not line:
          continue
        fields = _project(line.split("\t"), cols, src, line_no)
        outf.write(",".join(_intern_all(fields, ids)))
        outf.write("\n")
        rows += 1
    row_counts[out_name] = rows
    print(f"{out_name}: {rows} rows")

  consts = {key: ids[key] for key in CONST_KEYS}
  (out_dir / "ddisasm_consts.json").write_text(json.dumps(consts, indent=2) + "\n")
  (out_dir / "intern_stats.json").write_text(
    json.dumps(
      {
        "unique_tokens": len(ids),
        "row_counts": row_counts,
      },
      indent=2,
      sort_keys=True,
    )
    + "\n"
  )
  return consts


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("src_dir", type=Path)
  parser.add_argument("out_dir", type=Path)
  args = parser.parse_args()

  consts = convert(args.src_dir, args.out_dir)
  print(json.dumps({"ddisasm_consts": consts}, indent=2))
  return 0


if __name__ == "__main__":
  raise SystemExit(main())
