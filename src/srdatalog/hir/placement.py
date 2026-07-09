'''Lightweight SCC placement estimator for HIR programs.

This module is intentionally small: it does not alter lowering or codegen.
It gives us a concrete object to discuss the CPU/GPU boundary before wiring a
real placement pass into MIR.
'''

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from math import ceil

from srdatalog.hir.index import complete_index, get_arity
from srdatalog.hir.types import HirProgram, HirRuleVariant, HirStratum, Version


class ExecutionMode(str, Enum):
  '''Physical execution choices for one HIR stratum.'''

  GPU = "gpu"
  HOST_OR_STREAM = "host_or_stream"
  UNKNOWN = "unknown"


class IndexEstimatePolicy(str, Enum):
  '''Index-layout policies for placement experiments.

  These policies estimate memory pressure only; they do not rewrite the HIR or
  change generated code. `CANONICAL_ONLY` is an idealized lower bound for "keep
  one physical layout resident and rebuild/stream the rest on demand".
  '''

  DEFAULT = "default"
  CANONICAL_ONLY = "canonical-only"


@dataclass(frozen=True)
class RelationStats:
  '''Estimated row counts for one relation inside an SCC.'''

  full_rows: int
  delta_rows: int | None = None
  new_rows: int | None = None


@dataclass(frozen=True)
class PlacementBudget:
  '''Knobs for a conservative GPU memory estimate.

  `device_bytes` is multiplied by `safety_fraction` because kernels, temporary
  sort buffers, allocator fragmentation, and CUB/RMM scratch space also need
  VRAM. The default value type matches the current GPU encoded columns.
  '''

  device_bytes: int
  safety_fraction: float = 0.70
  value_bytes: int = 4
  provenance_bytes: int = 0
  index_overhead: float = 1.25
  default_delta_fraction: float = 0.10
  default_new_fraction: float = 0.10
  pcie_bandwidth_bytes_per_sec: float = 24.0 * 1024**3
  host_index_rows_per_sec: float = 150_000_000.0

  @property
  def usable_device_bytes(self) -> int:
    return int(self.device_bytes * self.safety_fraction)


@dataclass(frozen=True)
class IndexFootprint:
  relation: str
  version: Version
  index: tuple[int, ...]
  rows: int
  estimated_bytes: int


@dataclass(frozen=True)
class FallbackCost:
  '''Coarse CPU/host-stream fallback cost at an SCC boundary.

  `transfer_*` counts relation payload bytes, not physical index bytes. The
  model assumes a whole-stratum fallback: move needed inputs/results across the
  device boundary once, build needed host indexes, and then resume GPU strata.
  '''

  transfer_to_host_bytes: int
  transfer_to_device_bytes: int
  host_index_build_rows: int
  estimated_transfer_seconds: float
  estimated_host_index_seconds: float
  missing_relations: tuple[str, ...] = field(default_factory=tuple)

  @property
  def estimated_seconds(self) -> float:
    return self.estimated_transfer_seconds + self.estimated_host_index_seconds


@dataclass(frozen=True)
class StratumPlacement:
  stratum_index: int
  mode: ExecutionMode
  recursive: bool
  scc_members: tuple[str, ...]
  estimated_peak_bytes: int
  usable_device_bytes: int
  footprints: tuple[IndexFootprint, ...] = field(default_factory=tuple)
  reasons: tuple[str, ...] = field(default_factory=tuple)
  fallback_cost: FallbackCost | None = None


@dataclass(frozen=True)
class PlacementSummary:
  '''Peak working-set comparison between pure GPU and placed execution.

  This is a per-stratum peak estimate. It answers "what is the largest SCC
  working set the current all-GPU path would need?" and "what is the largest
  SCC working set still kept GPU-resident after placement?"
  '''

  pure_gpu_peak_bytes: int
  placed_gpu_peak_bytes: int
  host_or_stream_peak_bytes: int
  unknown_strata: int
  spilled_strata: int

  @property
  def device_peak_reduction_bytes(self) -> int:
    return max(0, self.pure_gpu_peak_bytes - self.placed_gpu_peak_bytes)

  @property
  def device_peak_reduction_fraction(self) -> float:
    if self.pure_gpu_peak_bytes == 0:
      return 0.0
    return self.device_peak_reduction_bytes / self.pure_gpu_peak_bytes


RelationRows = Mapping[str, int | RelationStats]


def _as_stats(value: int | RelationStats) -> RelationStats:
  if isinstance(value, RelationStats):
    return value
  return RelationStats(full_rows=value)


def _version_rows(stats: RelationStats, version: Version, budget: PlacementBudget) -> int:
  if version is Version.FULL:
    return stats.full_rows
  if version is Version.DELTA:
    if stats.delta_rows is not None:
      return stats.delta_rows
    return ceil(stats.full_rows * budget.default_delta_fraction)
  if stats.new_rows is not None:
    return stats.new_rows
  return ceil(stats.full_rows * budget.default_new_fraction)


def _index_bytes(rows: int, arity: int, budget: PlacementBudget) -> int:
  payload = rows * ((arity * budget.value_bytes) + budget.provenance_bytes)
  return ceil(payload * budget.index_overhead)


def _variant_indices(
  variants: list[HirRuleVariant],
  rel_name: str,
  arity: int,
  version: Version,
) -> set[tuple[int, ...]]:
  indices: set[tuple[int, ...]] = set()
  for variant in variants:
    for pattern in variant.access_patterns + variant.negation_patterns:
      if pattern.rel_name == rel_name and pattern.version is version:
        indices.add(tuple(complete_index(list(pattern.index_cols), arity)))
  return indices


def _variant_relations(variants: list[HirRuleVariant]) -> set[str]:
  rels: set[str] = set()
  for variant in variants:
    for pattern in variant.access_patterns + variant.negation_patterns:
      if pattern.rel_name:
        rels.add(pattern.rel_name)
  return rels


def _footprint(
  rel_name: str,
  version: Version,
  idx: tuple[int, ...],
  rows: int,
  arity: int,
  budget: PlacementBudget,
) -> IndexFootprint:
  return IndexFootprint(
    relation=rel_name,
    version=version,
    index=idx,
    rows=rows,
    estimated_bytes=_index_bytes(rows, arity, budget),
  )


def _policy_required_indices(
  *,
  policy: IndexEstimatePolicy,
  required: set[tuple[int, ...]],
  canonical: tuple[int, ...],
) -> set[tuple[int, ...]]:
  if policy is IndexEstimatePolicy.CANONICAL_ONLY:
    return {canonical}
  return set(required)


def _relation_payload_bytes(
  rel_name: str,
  relation_rows: RelationRows,
  hir: HirProgram,
  budget: PlacementBudget,
) -> int | None:
  raw_stats = relation_rows.get(rel_name)
  if raw_stats is None:
    return None
  stats = _as_stats(raw_stats)
  arity = get_arity(rel_name, hir.relation_decls)
  return stats.full_rows * arity * budget.value_bytes


def _fallback_cost(
  stratum: HirStratum,
  footprints: tuple[IndexFootprint, ...],
  relation_rows: RelationRows,
  hir: HirProgram,
  budget: PlacementBudget,
) -> FallbackCost | None:
  variants = stratum.recursive_variants if stratum.is_recursive else stratum.base_variants
  accessed = _variant_relations(variants)
  produced = set(stratum.scc_members)

  transfer_to_host = 0
  transfer_to_device = 0
  missing: set[str] = set()
  for rel_name in sorted(accessed):
    payload = _relation_payload_bytes(rel_name, relation_rows, hir, budget)
    if payload is None:
      missing.add(rel_name)
    else:
      transfer_to_host += payload
  for rel_name in sorted(produced):
    payload = _relation_payload_bytes(rel_name, relation_rows, hir, budget)
    if payload is None:
      missing.add(rel_name)
    else:
      transfer_to_device += payload

  build_rows = sum(f.rows for f in footprints)
  transfer_seconds = (
    (transfer_to_host + transfer_to_device) / budget.pcie_bandwidth_bytes_per_sec
    if budget.pcie_bandwidth_bytes_per_sec > 0
    else 0.0
  )
  host_index_seconds = (
    build_rows / budget.host_index_rows_per_sec if budget.host_index_rows_per_sec > 0 else 0.0
  )
  return FallbackCost(
    transfer_to_host_bytes=transfer_to_host,
    transfer_to_device_bytes=transfer_to_device,
    host_index_build_rows=build_rows,
    estimated_transfer_seconds=transfer_seconds,
    estimated_host_index_seconds=host_index_seconds,
    missing_relations=tuple(sorted(missing)),
  )


def _stratum_footprints(
  stratum: HirStratum,
  relation_rows: RelationRows,
  hir: HirProgram,
  budget: PlacementBudget,
  index_policy: IndexEstimatePolicy,
) -> tuple[tuple[IndexFootprint, ...], tuple[str, ...]]:
  footprints: list[IndexFootprint] = []
  reasons: list[str] = []

  for rel_name in sorted(stratum.scc_members):
    raw_stats = relation_rows.get(rel_name)
    if raw_stats is None:
      reasons.append(f"{rel_name}: missing row-count estimate")
      continue

    stats = _as_stats(raw_stats)
    arity = get_arity(rel_name, hir.relation_decls)
    required = {
      tuple(complete_index(list(idx), arity))
      for idx in stratum.required_indices.get(rel_name, [list(range(arity))])
    }
    canonical = tuple(
      complete_index(stratum.canonical_index.get(rel_name, list(range(arity))), arity)
    )
    policy_required = _policy_required_indices(
      policy=index_policy,
      required=required,
      canonical=canonical,
    )

    if stratum.is_recursive:
      variants = stratum.recursive_variants
      full_indices = _variant_indices(variants, rel_name, arity, Version.FULL)
      full_indices.add(canonical)
      full_indices = _policy_required_indices(
        policy=index_policy,
        required=full_indices,
        canonical=canonical,
      )
      delta_indices = set(policy_required)
      new_indices = {canonical}
    else:
      # Non-recursive strata still materialize NEW, DELTA, then FULL during
      # simple maintenance. This is a conservative peak estimate.
      full_indices = set(policy_required)
      delta_indices = set(policy_required)
      new_indices = {canonical}

    for version, indices in (
      (Version.FULL, full_indices),
      (Version.DELTA, delta_indices),
      (Version.NEW, new_indices),
    ):
      rows = _version_rows(stats, version, budget)
      for idx in sorted(indices):
        footprints.append(_footprint(rel_name, version, idx, rows, arity, budget))

    if len(required) > 1:
      reasons.append(f"{rel_name}: maintains {len(required)} physical index layouts")
      if index_policy is IndexEstimatePolicy.CANONICAL_ONLY:
        reasons.append(
          f"{rel_name}: canonical-only estimate keeps 1 layout and treats others as rebuilds"
        )
    if arity >= 4:
      reasons.append(f"{rel_name}: arity {arity} makes every index row wide")

  return tuple(footprints), tuple(reasons)


def estimate_hir_placement(
  hir: HirProgram,
  relation_rows: RelationRows,
  budget: PlacementBudget,
  index_policy: IndexEstimatePolicy | str = IndexEstimatePolicy.DEFAULT,
) -> list[StratumPlacement]:
  '''Estimate physical placement for every HIR stratum.

  The returned values are guidance, not proof. They are deliberately
  conservative for GPU memory because the runtime also allocates sort buffers,
  per-kernel output buffers, RMM pool overhead, and transient views.
  '''

  if isinstance(index_policy, str):
    index_policy = IndexEstimatePolicy(index_policy)

  placements: list[StratumPlacement] = []
  for idx, stratum in enumerate(hir.strata):
    footprints, reasons = _stratum_footprints(
      stratum,
      relation_rows,
      hir,
      budget,
      index_policy,
    )
    peak = sum(f.estimated_bytes for f in footprints)
    reasons_list = list(reasons)
    fallback = _fallback_cost(stratum, footprints, relation_rows, hir, budget)

    if reasons and any("missing row-count" in reason for reason in reasons):
      mode = ExecutionMode.UNKNOWN
    elif peak <= budget.usable_device_bytes:
      mode = ExecutionMode.GPU
    else:
      mode = ExecutionMode.HOST_OR_STREAM
      reasons_list.append(
        "estimated index working set exceeds usable device memory "
        f"({format_bytes(peak)} > {format_bytes(budget.usable_device_bytes)})"
      )

    if stratum.is_recursive:
      reasons_list.append("recursive SCC must keep FULL/DELTA/NEW maintenance state coherent")

    placements.append(
      StratumPlacement(
        stratum_index=idx,
        mode=mode,
        recursive=stratum.is_recursive,
        scc_members=tuple(sorted(stratum.scc_members)),
        estimated_peak_bytes=peak,
        usable_device_bytes=budget.usable_device_bytes,
        footprints=footprints,
        reasons=tuple(reasons_list),
        fallback_cost=fallback,
      )
    )

  return placements


def summarize_placement(placements: list[StratumPlacement]) -> PlacementSummary:
  known = [p for p in placements if p.mode is not ExecutionMode.UNKNOWN]
  gpu = [p for p in known if p.mode is ExecutionMode.GPU]
  host_or_stream = [p for p in known if p.mode is ExecutionMode.HOST_OR_STREAM]

  return PlacementSummary(
    pure_gpu_peak_bytes=max((p.estimated_peak_bytes for p in known), default=0),
    placed_gpu_peak_bytes=max((p.estimated_peak_bytes for p in gpu), default=0),
    host_or_stream_peak_bytes=max(
      (p.estimated_peak_bytes for p in host_or_stream),
      default=0,
    ),
    unknown_strata=sum(1 for p in placements if p.mode is ExecutionMode.UNKNOWN),
    spilled_strata=len(host_or_stream),
  )


def format_bytes(value: int) -> str:
  units = ("B", "KiB", "MiB", "GiB", "TiB")
  amount = float(value)
  for unit in units:
    if amount < 1024.0 or unit == units[-1]:
      return f"{amount:.1f} {unit}"
    amount /= 1024.0
  return f"{value} B"


def format_placement_report(placements: list[StratumPlacement]) -> str:
  lines: list[str] = []
  for placement in placements:
    members = ", ".join(placement.scc_members) or "<empty>"
    kind = "recursive" if placement.recursive else "base"
    lines.append(
      f"stratum {placement.stratum_index} [{kind}] {placement.mode.value}: "
      f"{members} peak={format_bytes(placement.estimated_peak_bytes)}"
    )
    for reason in placement.reasons:
      lines.append(f"  - {reason}")
    if placement.mode is ExecutionMode.HOST_OR_STREAM and placement.fallback_cost is not None:
      cost = placement.fallback_cost
      lines.append(
        "  - fallback estimate: "
        f"H2D/D2H payload={format_bytes(cost.transfer_to_device_bytes)} + "
        f"{format_bytes(cost.transfer_to_host_bytes)}, "
        f"host index rows={cost.host_index_build_rows:,}, "
        f"time~{cost.estimated_seconds:.2f}s "
        f"(transfer {cost.estimated_transfer_seconds:.2f}s, "
        f"host-index {cost.estimated_host_index_seconds:.2f}s)"
      )
      if cost.missing_relations:
        preview = ", ".join(cost.missing_relations[:5])
        suffix = "" if len(cost.missing_relations) <= 5 else ", ..."
        lines.append(f"  - fallback estimate missing row counts for: {preview}{suffix}")
  return "\n".join(lines)


def format_placement_summary(summary: PlacementSummary) -> str:
  reduction = summary.device_peak_reduction_fraction * 100.0
  return "\n".join(
    [
      "placement summary:",
      f"  pure GPU peak working set: {format_bytes(summary.pure_gpu_peak_bytes)}",
      f"  placed GPU peak working set: {format_bytes(summary.placed_gpu_peak_bytes)}",
      f"  host/stream peak working set: {format_bytes(summary.host_or_stream_peak_bytes)}",
      f"  device peak reduction: {format_bytes(summary.device_peak_reduction_bytes)} "
      f"({reduction:.1f}%)",
      f"  spilled strata: {summary.spilled_strata}",
      f"  unknown strata: {summary.unknown_strata}",
    ]
  )
