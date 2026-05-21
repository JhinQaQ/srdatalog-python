"""05_multi_head_and_named.py — multi-head rules and naming.

What this shows:
  - `.named("RuleName")` attaches a stable name used in C++ symbol
    names + debugging.
  - `(A | B | C) <= body` builds a rule with multiple heads, all
    derived from the same body.

  Logical meaning:
    InDegree(y), OutDegree(x) :- Edge(x, y)

  (Each edge contributes simultaneously to InDegree and OutDegree.
   In practice you would aggregate these — this example is just to
   show the multi-head syntax.)

Run:
  uv run python notes/examples/05_multi_head_and_named.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var


def main() -> None:
  x, y = Var("x"), Var("y")

  Edge = Relation("Edge", 2)
  InDegree = Relation("InDegree", 1)
  OutDegree = Relation("OutDegree", 1)

  rule = (InDegree(y) | OutDegree(x) <= Edge(x, y)).named("DegreeFromEdge")

  program = Program(rules=[rule])

  print("=== Rule ===")
  print(f"  name      = {program.rules[0].name}")
  print(f"  heads     = {[a.rel for a in program.rules[0].heads]}")
  print(f"  body[0]   = {program.rules[0].body[0]}")

  print("\nRelations:")
  for r in program.relations:
    print(f"  {r.name}({r.arity})")


if __name__ == "__main__":
  main()
