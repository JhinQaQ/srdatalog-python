"""03_filters_and_constants.py — filters and constants in atoms.

What this shows:
  - Using a bare Python `int` as a constant argument to a relation
    (the DSL auto-coerces it to a Const).
  - Using an explicit `Filter((var,), "return ...;")` to inject a
    C++ predicate over bound variables.

  Logical meaning:
    BigEdge(x, y) :- Edge(x, y), x > 100
    StartsAtRoot(y) :- Edge(0, y)

Run:
  uv run python notes/examples/03_filters_and_constants.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var
from srdatalog.dsl import Const, Filter


def main() -> None:
  x, y = Var("x"), Var("y")

  Edge = Relation("Edge", 2)
  BigEdge = Relation("BigEdge", 2)
  StartsAtRoot = Relation("StartsAtRoot", 1)

  big_edge_rule = (
    BigEdge(x, y) <= Edge(x, y) & Filter(("x",), "return x > 100;")
  ).named("BigEdge")

  starts_at_root_rule = (StartsAtRoot(y) <= Edge(Const(0), y)).named("StartsAtRoot")

  program = Program(rules=[big_edge_rule, starts_at_root_rule])

  print("=== Rules ===")
  for r in program.rules:
    body_kinds = [type(c).__name__ for c in r.body]
    print(f"  {r.name}: body clause kinds = {body_kinds}")

  print(
    "\nNote: the constant rewrite pass in HIR will turn `Edge(Const(0), y)` "
    "into `Edge(_c0, y) & Filter((_c0,), 'return _c0 == 0;')` automatically."
  )


if __name__ == "__main__":
  main()
