"""09_ir_translation_walkthrough.py - translate small programs across IRs.

What this shows:
  - Read one rule as Python DSL, Datalog text, HIR, and MIR.
  - HIR adds planning information: strata, variants, access patterns.
  - MIR: execute-pipeline, fixpoint-plan, compute-delta-index, merge-index.

This file adds ./src to sys.path so it works from a fresh clone without
installing the package first. It does not emit C++ and does not need CUDA.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
  sys.path.insert(0, str(SRC))

from srdatalog import Program, Relation, Var, compile_to_hir, compile_to_mir
from srdatalog.dsl import Atom, ClauseArg, Filter, Negation
from srdatalog.hir.types import HirProgram, HirRuleVariant
from srdatalog.mir.emit import print_mir_sexpr
from srdatalog.mir.types import (
  ExecutePipeline,
  FixpointPlan,
  MirNode,
  ParallelGroup,
  Program as MirProgram,
)


def divider(title: str) -> None:
  print("\n" + "=" * 88)
  print(title)
  print("=" * 88)


def small(title: str) -> None:
  print("\n" + title)
  print("-" * len(title))


def arg_text(arg: ClauseArg) -> str:
  if arg.var_name is not None:
    return arg.var_name
  if arg.const_cpp_expr is not None:
    return arg.const_cpp_expr
  if arg.cpp_code is not None:
    return "{" + arg.cpp_code + "}"
  return "?"


def atom_text(atom: Atom) -> str:
  return atom.rel + "(" + ", ".join(arg_text(arg) for arg in atom.args) + ")"


def clause_text(clause) -> str:
  if isinstance(clause, Atom):
    return atom_text(clause)
  if isinstance(clause, Negation):
    return "not " + atom_text(clause.atom)
  if isinstance(clause, Filter):
    return "filter(" + ", ".join(clause.vars) + "): " + clause.code
  return repr(clause)


def print_source_ir(program: Program, hand_datalog: str, hand_logical: str) -> None:
  small("IR 0: hand-written Datalog")
  print(hand_datalog)

  small("IR 1: Python DSL objects")
  print("The DSL builds Rule/Atom objects (not executing the query).")
  for rule in program.rules:
    heads = " | ".join(atom_text(head) for head in rule.heads)
    body = ", ".join(clause_text(clause) for clause in rule.body)
    print(f"  {rule.name}: {heads} <= {body}")

  small("IR 1.5: logical operator, handwritten")
  print(hand_logical)


def explain_hir_variant(variant: HirRuleVariant, kind: str) -> None:
  name = variant.original_rule.name
  print(f"  {kind} variant for rule {name!r}")
  if variant.delta_idx >= 0:
    print(f"    delta_idx      = {variant.delta_idx}")
  print(f"    clause_order   = {variant.clause_order}")
  print(f"    var_order      = {variant.var_order}")
  print(f"    clause_versions= {[v.value for v in variant.clause_versions]}")
  if not variant.access_patterns:
    print("    access_patterns= []")
  for access in variant.access_patterns:
    prefix_vars = access.access_order[: access.prefix_len]
    print(
      "    access_pattern = "
      f"rel={access.rel_name} ver={access.version.value} "
      f"index_cols={access.index_cols} access_order={access.access_order} "
      f"bound_prefix={prefix_vars}"
    )
  for neg in variant.negation_patterns:
    prefix_vars = neg.access_order[: neg.prefix_len]
    print(
      "    negation       = "
      f"rel={neg.rel_name} ver={neg.version.value} "
      f"index_cols={neg.index_cols} access_order={neg.access_order} "
      f"bound_prefix={prefix_vars}"
    )


def print_hir_ir(hir: HirProgram) -> None:
  small("IR 2: actual HIR summary from compile_to_hir")
  print("HIR keeps the rule meaning, but adds compiler analysis.")
  print("Relations:")
  for decl in hir.relation_decls:
    flags = []
    if decl.input_file:
      flags.append(f"input_file={decl.input_file!r}")
    if decl.print_size:
      flags.append("print_size=True")
    suffix = " (" + ", ".join(flags) + ")" if flags else ""
    print(f"  {decl.rel_name}/{len(decl.types)}{suffix}")

  print("\nStrata:")
  for i, stratum in enumerate(hir.strata):
    print(
      f"  stratum {i}: recursive={stratum.is_recursive} "
      f"relations={sorted(stratum.scc_members)}"
    )
    if stratum.required_indices:
      print(f"    required_indices = {stratum.required_indices}")
    if stratum.canonical_index:
      print(f"    canonical_index  = {stratum.canonical_index}")
    for variant in stratum.base_variants:
      explain_hir_variant(variant, "base")
    for variant in stratum.recursive_variants:
      explain_hir_variant(variant, "recursive")

  print(
    "\nKey HIR idea: versions are relation versions, not time versions. "
    "FULL means accumulated facts, DELTA means facts produced last round, "
    "and NEW means the candidate facts just produced by this pipeline."
  )


def summarize_mir_node(node: MirNode, indent: int = 0) -> None:
  pad = "  " * indent
  if isinstance(node, ExecutePipeline):
    print(f"{pad}- ExecutePipeline rule={node.rule_name}")
    print(f"{pad}  sources={len(node.source_specs)} dests={len(node.dest_specs)}")
    print(f"{pad}  body ops:")
    for op in node.pipeline:
      print(f"{pad}    * {type(op).__name__}")
    return

  if isinstance(node, FixpointPlan):
    print(f"{pad}- FixpointPlan")
    for child in node.instructions:
      summarize_mir_node(child, indent + 1)
    return

  if isinstance(node, ParallelGroup):
    print(f"{pad}- ParallelGroup")
    for child in node.ops:
      summarize_mir_node(child, indent + 1)
    return

  print(f"{pad}- {type(node).__name__}")


def print_mir_ir(mir: MirProgram, show_sexpr: bool = True) -> None:
  small("IR 3: actual MIR summary from compile_to_mir")
  print("MIR is close to an execution plan. Codegen walks these steps.")
  for i, (step, is_recursive) in enumerate(mir.steps):
    print(f"  step {i}: recursive={is_recursive}")
    summarize_mir_node(step, indent=2)

  print(
    "\nKey MIR idea: a rule body becomes a pipeline. Recursive strata become "
    "fixpoint plans with bookkeeping around the pipeline: rebuild indexes, "
    "compute DELTA from NEW, clear temporary NEW, then merge DELTA into FULL."
  )

  if show_sexpr:
    small("Actual MIR S-expression")
    print(print_mir_sexpr(mir))


def example_two_hop() -> Program:
  x, y, z = Var("x"), Var("y"), Var("z")
  Edge = Relation("Edge", 2, input_file="Edge.csv")
  TwoHop = Relation("TwoHop", 2, print_size=True)

  return Program(
    rules=[
      (TwoHop(x, z) <= Edge(x, y) & Edge(y, z)).named("TwoHop"),
    ],
  )


def example_tc() -> Program:
  x, y, z = Var("x"), Var("y"), Var("z")
  Edge = Relation("Edge", 2, input_file="Edge.csv")
  Path = Relation("Path", 2, print_size=True)

  return Program(
    rules=[
      (Path(x, y) <= Edge(x, y)).named("PathBase"),
      (Path(x, z) <= Path(x, y) & Edge(y, z)).named("PathRec"),
    ],
  )


def example_antijoin() -> Program:
  x, y = Var("x"), Var("y")
  Node = Relation("Node", 1, input_file="Node.csv")
  Edge = Relation("Edge", 2, input_file="Edge.csv")
  HasOutgoing = Relation("HasOutgoing", 1)
  Sink = Relation("Sink", 1, print_size=True)

  return Program(
    rules=[
      (HasOutgoing(x) <= Edge(x, y)).named("HasOutgoing"),
      (Sink(x) <= Node(x) & ~HasOutgoing(x)).named("Sink"),
    ],
  )


def run_example(title: str, program: Program, hand_datalog: str, hand_logical: str) -> None:
  divider(title)
  print_source_ir(program, hand_datalog, hand_logical)
  hir = compile_to_hir(program)
  print_hir_ir(hir)
  mir = compile_to_mir(program)
  print_mir_ir(mir, show_sexpr=True)


def main() -> None:
  run_example(
    "Example A: non-recursive two-hop query",
    example_two_hop(),
    hand_datalog=(
      "TwoHop(x, z) :- Edge(x, y), Edge(y, z).\n\n"
      "Meaning: x reaches z in exactly two edges, through middle node y."
    ),
    hand_logical=(
      "TwoHop = project(x, z)(\n"
      "  join Edge(x, y) with Edge(y, z) on shared variable y\n"
      ")\n\n"
      "This is one stratum and one non-recursive pipeline."
    ),
  )

  run_example(
    "Example B: recursive transitive closure",
    example_tc(),
    hand_datalog=(
      "Path(x, y) :- Edge(x, y).\n"
      "Path(x, z) :- Path(x, y), Edge(y, z).\n\n"
      "Meaning: Path starts with direct edges, then recursively extends "
      "already-known paths by one edge."
    ),
    hand_logical=(
      "Path_FULL initially receives direct edges from PathBase.\n"
      "Then the recursive stratum repeats:\n"
      "  Path_NEW = project(x, z)(join Path_DELTA(x, y), Edge_FULL(y, z))\n"
      "  Path_DELTA = Path_NEW - Path_FULL\n"
      "  Path_FULL = Path_FULL union Path_DELTA\n"
      "until Path_DELTA is empty."
    ),
  )

  run_example(
    "Example C: stratified negation / anti-join",
    example_antijoin(),
    hand_datalog=(
      "HasOutgoing(x) :- Edge(x, y).\n"
      "Sink(x) :- Node(x), not HasOutgoing(x).\n\n"
      "Meaning: a sink is a node with no outgoing edge."
    ),
    hand_logical=(
      "First stratum:\n"
      "  HasOutgoing = project(x)(Edge)\n\n"
      "Second stratum:\n"
      "  Sink = Node anti-join HasOutgoing on x\n\n"
      "The negated relation must be complete before Sink can read it."
    ),
  )


if __name__ == "__main__":
  main()
