"""01_hello.py — the smallest possible srdatalog program.

Goal:
  Build a Program in Python and just inspect it. No HIR, no MIR,
  no C++ codegen. This is the bare DSL.

Run:
  uv run python notes/examples/01_hello.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var


def main() -> None:
  x = Var("x")
  y = Var("y")

  Edge = Relation("Edge", 2)
  Reachable = Relation("Reachable", 2)

  rule = (Reachable(x, y) <= Edge(x, y)).named("Base")

  program = Program(rules=[rule])

  print("=== Program object ===")
  print(program)

  print("\n=== Relations auto-derived from rules ===")
  for r in program.relations:
    print(f"  {r.name}  arity={r.arity}")

  print("\n=== Rules ===")
  for r in program.rules:
    print(f"  {r.name}: heads={[a.rel for a in r.heads]} body={[c for c in r.body]}")


if __name__ == "__main__":
  main()
