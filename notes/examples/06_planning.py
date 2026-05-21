"""06_planning.py — hint the join planner with `.with_plan(...)`.

What this shows:
  - A triangle pattern (3-way join).
  - `.with_plan(var_order=["x", "y", "z"])` tells HIR which order to
    bind variables when planning the join. The planner would normally
    pick its own order; this forces it.

  Logical meaning:
    Triangle(x, y, z) :- R(x, y), S(y, z), T(z, x)

Run:
  uv run python notes/examples/06_planning.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var


def main() -> None:
  x, y, z = Var("x"), Var("y"), Var("z")

  R = Relation("R", 2)
  S = Relation("S", 2)
  T = Relation("T", 2)
  Triangle = Relation("Triangle", 3, print_size=True)

  rule = (
    (Triangle(x, y, z) <= R(x, y) & S(y, z) & T(z, x))
    .named("Triangle")
    .with_plan(var_order=["x", "y", "z"])
  )

  program = Program(rules=[rule])

  print("=== Triangle rule ===")
  for plan in program.rules[0].plans:
    print(f"  plan: delta={plan.delta} var_order={plan.var_order}")

  print(
    "\nWith `var_order=['x','y','z']`, the planner will scan R first "
    "(bound on x), then S (joined on y), then T (joined on z,x). "
    "Try removing .with_plan() to let the planner pick."
  )


if __name__ == "__main__":
  main()
