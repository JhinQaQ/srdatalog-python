"""07_inspect_hir_mir.py — peek at HIR and MIR.

What this shows:
  - `compile_to_hir(program)` produces a HirProgram with strata,
    relation decls, and rule variants.
  - `compile_to_mir(program)` produces a sequence of MIR steps
    (pipelines + fixpoints) that codegen will turn into C++.

  This is the *frontend* of the compiler — no C++ is emitted here.

Run:
  uv run python notes/examples/07_inspect_hir_mir.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var, compile_to_hir, compile_to_mir


def build_program() -> Program:
  x, y, z = Var("x"), Var("y"), Var("z")
  Edge = Relation("Edge", 2)
  Path = Relation("Path", 2, print_size=True)
  return Program(rules=[
    (Path(x, y) <= Edge(x, y)).named("PathBase"),
    (Path(x, z) <= Path(x, y) & Edge(y, z)).named("PathRec"),
  ])


def main() -> None:
  program = build_program()

  hir = compile_to_hir(program)
  print("=== HIR ===")
  print(f"  relation_decls = {[d.rel_name for d in hir.relation_decls]}")
  print(f"  num strata     = {len(hir.strata)}")
  for i, s in enumerate(hir.strata):
    base = [v.original_rule.name for v in s.base_variants]
    rec = [v.original_rule.name for v in s.recursive_variants]
    print(
      f"    stratum {i}: scc={sorted(s.scc_members)} "
      f"recursive={s.is_recursive} base={base} rec={rec}"
    )

  mir = compile_to_mir(program)
  print("\n=== MIR ===")
  print(f"  num steps = {len(mir.steps)}")
  for i, (step, is_rec) in enumerate(mir.steps):
    print(f"  step {i}: type={type(step).__name__} recursive={is_rec}")

  print(
    "\nHIR is the planned-but-still-logical view. MIR is the imperative "
    "step sequence the codegen walks to emit C++. Open "
    "src/srdatalog/hir/types.py and src/srdatalog/mir/types.py for the "
    "full data shapes."
  )


if __name__ == "__main__":
  main()
