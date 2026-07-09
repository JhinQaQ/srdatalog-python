from srdatalog.dsl import Program, Relation, Var
from srdatalog.hir import compile_to_hir
from srdatalog.hir.placement import (
  ExecutionMode,
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


def test_path_compose_small_scc_fits_gpu_budget():
  hir = compile_to_hir(build_path_compose_program())
  budget = PlacementBudget(device_bytes=24 * 1024**3)

  placements = estimate_hir_placement(
    hir,
    {"Path": RelationStats(full_rows=1_000_000, delta_rows=100_000, new_rows=100_000)},
    budget,
  )

  assert placements[1].mode is ExecutionMode.GPU


def test_path_compose_massive_scc_prefers_host_or_stream():
  hir = compile_to_hir(build_path_compose_program())
  budget = PlacementBudget(device_bytes=24 * 1024**3)

  placements = estimate_hir_placement(
    hir,
    {"Path": RelationStats(full_rows=2_000_000_000, delta_rows=50_000_000, new_rows=50_000_000)},
    budget,
  )
  report = format_placement_report(placements)

  assert placements[1].mode is ExecutionMode.HOST_OR_STREAM
  assert "Path: maintains 2 physical index layouts" in report
  assert "exceeds usable device memory" in report
  assert "fallback estimate" in report
  assert placements[1].fallback_cost is not None
  assert placements[1].fallback_cost.transfer_to_host_bytes > 0
  assert placements[1].fallback_cost.transfer_to_device_bytes > 0

  summary = summarize_placement(placements)
  summary_report = format_placement_summary(summary)

  assert summary.pure_gpu_peak_bytes > budget.usable_device_bytes
  assert summary.placed_gpu_peak_bytes == 0
  assert summary.host_or_stream_peak_bytes == summary.pure_gpu_peak_bytes
  assert summary.device_peak_reduction_bytes == summary.pure_gpu_peak_bytes
  assert "device peak reduction" in summary_report


def test_missing_relation_stats_make_placement_unknown():
  hir = compile_to_hir(build_path_compose_program())
  budget = PlacementBudget(device_bytes=24 * 1024**3)

  placements = estimate_hir_placement(hir, {}, budget)

  assert placements[1].mode is ExecutionMode.UNKNOWN
  assert any(reason == "Path: missing row-count estimate" for reason in placements[1].reasons)


def test_canonical_only_index_estimate_reduces_peak():
  hir = compile_to_hir(build_path_compose_program())
  budget = PlacementBudget(device_bytes=24 * 1024**3)
  rows = {
    "Path": RelationStats(full_rows=2_000_000_000, delta_rows=50_000_000, new_rows=50_000_000)
  }

  default = estimate_hir_placement(
    hir,
    rows,
    budget,
    index_policy=IndexEstimatePolicy.DEFAULT,
  )
  canonical_only = estimate_hir_placement(
    hir,
    rows,
    budget,
    index_policy=IndexEstimatePolicy.CANONICAL_ONLY,
  )
  report = format_placement_report(canonical_only)

  assert canonical_only[1].estimated_peak_bytes < default[1].estimated_peak_bytes
  assert "canonical-only estimate keeps 1 layout" in report
