"""Estimate which SCCs should stay on GPU versus spill to host/streaming.

The row counts here are deliberately synthetic. Replace them with counts from
your dataset CSVs when you want a real placement report.

Run:

    PYTHONPATH=src:examples python examples/scc_placement_estimate.py
    PYTHONPATH=src:examples python examples/scc_placement_estimate.py --benchmark ddisasm
    PYTHONPATH=src:examples python examples/scc_placement_estimate.py --compare-index-policies
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from srdatalog.dsl import Program, Relation, Var
from srdatalog.hir import compile_to_hir
from srdatalog.hir.placement import (
  IndexEstimatePolicy,
  PlacementBudget,
  RelationStats,
  estimate_hir_placement,
  format_placement_report,
  format_placement_summary,
  summarize_placement,
)


def build_path_compose_program() -> Program:
  x, y, z = Var("x"), Var("y"), Var("z")
  seed = Relation("Seed", 2)
  path = Relation("Path", 2)
  return Program(
    rules=[
      (path(x, y) <= seed(x, y)).named("PathSeed"),
      (path(x, z) <= path(x, y) & path(y, z)).named("PathCompose"),
    ],
  )


def path_compose_rows() -> dict[str, RelationStats]:
  return {
    # A transitive closure can approach |V|^2. At 2B pairs, even one
    # full-arity GPU index is already large; two layouts are worse.
    "Path": RelationStats(full_rows=2_000_000_000, delta_rows=50_000_000, new_rows=50_000_000),
  }


def cspa_rows() -> dict[str, RelationStats]:
  return {
    "ValueFlow": RelationStats(full_rows=1_000_000_000, delta_rows=30_000_000),
    "ValueAlias": RelationStats(full_rows=800_000_000, delta_rows=20_000_000),
    "MemoryAlias": RelationStats(full_rows=700_000_000, delta_rows=20_000_000),
  }


def ddisasm_rows() -> dict[str, RelationStats]:
  return {
    # Register liveness/def-use SCC: block/instruction x register x use/def sites.
    "RegDefUseDefUsed": RelationStats(full_rows=900_000_000, delta_rows=20_000_000),
    "RegDefUseLiveVarAtBlockEnd": RelationStats(full_rows=700_000_000, delta_rows=20_000_000),
    "RegDefUseLiveVarAtPriorUsed": RelationStats(full_rows=700_000_000, delta_rows=20_000_000),
    "RegDefUseLiveVarUsed": RelationStats(full_rows=500_000_000, delta_rows=10_000_000),
    "RegDefUseReturnValUsed": RelationStats(full_rows=100_000_000, delta_rows=5_000_000),
    # Stack def-use relations are wider, so fewer rows can still be expensive.
    "StackDefUseDefUsed": RelationStats(full_rows=350_000_000, delta_rows=10_000_000),
    "StackDefUseLiveVarAtBlockEnd": RelationStats(full_rows=250_000_000, delta_rows=10_000_000),
    "StackDefUseLiveVarAtPriorUsed": RelationStats(full_rows=250_000_000, delta_rows=10_000_000),
    "DefUsedForAddress": RelationStats(full_rows=300_000_000, delta_rows=10_000_000),
  }


def _load_rows_json(path: Path) -> dict[str, RelationStats]:
  raw = json.load(path.open(encoding="utf-8"))
  out: dict[str, RelationStats] = {}
  for rel_name, value in raw.items():
    if isinstance(value, int):
      out[rel_name] = RelationStats(full_rows=value)
    elif isinstance(value, dict):
      out[rel_name] = RelationStats(
        full_rows=int(value["full_rows"]),
        delta_rows=int(value["delta_rows"]) if value.get("delta_rows") is not None else None,
        new_rows=int(value["new_rows"]) if value.get("new_rows") is not None else None,
      )
    else:
      raise TypeError(f"unsupported row stats for {rel_name}: {value!r}")
  return out


def _build_examples() -> list[tuple[str, Program, dict[str, RelationStats]]]:
  examples: list[tuple[str, Program, dict[str, RelationStats]]] = [
    ("path-compose", build_path_compose_program(), path_compose_rows()),
  ]

  try:
    from cspa import build_cspa_db_program

    examples.append(("cspa", build_cspa_db_program(), cspa_rows()))
  except Exception as exc:
    print(f"skip cspa: {exc}")

  try:
    from ddisasm import build_ddisasmdb_program

    meta = {"LOAD": 1, "NONE": 0, "PCRelative": 2, "STORE": 3}
    examples.append(("ddisasm", build_ddisasmdb_program(meta), ddisasm_rows()))
  except Exception as exc:
    print(f"skip ddisasm: {exc}")

  return examples


def _print_report(
  name: str,
  program: Program,
  rows: dict[str, RelationStats],
  budget: PlacementBudget,
  index_policy: IndexEstimatePolicy,
) -> None:
  print(f"\n== {name} [{index_policy.value}] ==")
  hir = compile_to_hir(program)
  placements = estimate_hir_placement(hir, rows, budget, index_policy=index_policy)
  interesting = [
    p
    for p in placements
    if p.recursive or p.mode.value != "unknown" or p.estimated_peak_bytes > 0
  ]
  print(format_placement_report(interesting))
  print(format_placement_summary(summarize_placement(interesting)))


def main() -> None:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--benchmark",
    default="all",
    choices=["all", "path-compose", "cspa", "ddisasm"],
    help="Benchmark to report (default: all).",
  )
  parser.add_argument(
    "--device-gib",
    type=float,
    default=24.0,
    help="Physical GPU memory in GiB for the estimate.",
  )
  parser.add_argument(
    "--safety-fraction",
    type=float,
    default=0.70,
    help="Fraction of GPU memory considered usable for persistent indexes.",
  )
  parser.add_argument(
    "--index-policy",
    choices=[p.value for p in IndexEstimatePolicy],
    default=IndexEstimatePolicy.DEFAULT.value,
    help="Index memory policy to estimate.",
  )
  parser.add_argument(
    "--compare-index-policies",
    action="store_true",
    help="Print default and canonical-only estimates for each selected benchmark.",
  )
  parser.add_argument(
    "--pcie-gbps",
    type=float,
    default=24.0,
    help="Boundary transfer bandwidth in GiB/s for fallback estimates.",
  )
  parser.add_argument(
    "--host-index-mrows-sec",
    type=float,
    default=150.0,
    help="Host index build throughput in million rows/s for fallback estimates.",
  )
  parser.add_argument(
    "--rows-json",
    default="",
    help=(
      "Optional relation row-count JSON for the selected benchmark. Values may be "
      "integers or objects with full_rows/delta_rows/new_rows."
    ),
  )
  args = parser.parse_args()

  budget = PlacementBudget(
    device_bytes=int(args.device_gib * 1024**3),
    safety_fraction=args.safety_fraction,
    pcie_bandwidth_bytes_per_sec=args.pcie_gbps * 1024**3,
    host_index_rows_per_sec=args.host_index_mrows_sec * 1_000_000,
  )

  examples = _build_examples()
  if args.benchmark != "all":
    examples = [entry for entry in examples if entry[0] == args.benchmark]
  if not examples:
    raise RuntimeError(f"no benchmark loaded for {args.benchmark!r}")

  override_rows = _load_rows_json(Path(args.rows_json)) if args.rows_json else None
  policies = (
    [IndexEstimatePolicy.DEFAULT, IndexEstimatePolicy.CANONICAL_ONLY]
    if args.compare_index_policies
    else [IndexEstimatePolicy(args.index_policy)]
  )

  for name, program, rows in examples:
    effective_rows = override_rows if override_rows is not None else rows
    for policy in policies:
      _print_report(name, program, effective_rows, budget, policy)


if __name__ == "__main__":
  main()
