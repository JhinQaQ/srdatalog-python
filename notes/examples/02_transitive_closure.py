"""02_transitive_closure.py — recursion: the textbook Datalog example.

What this shows:
  - Two rules, one base and one recursive.
  - The recursive rule references `Path` on BOTH sides — that triggers
    semi-naive evaluation in HIR.

  Logical meaning:
    Path(x, y) :- Edge(x, y)
    Path(x, z) :- Path(x, y), Edge(y, z)

Run:
  uv run python notes/examples/02_transitive_closure.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var


def main() -> None:
  x, y, z = Var("x"), Var("y"), Var("z")

  Edge = Relation("Edge", 2)
  Path = Relation("Path", 2, print_size=True)

  base = (Path(x, y) <= Edge(x, y)).named("PathBase")
  rec = (Path(x, z) <= Path(x, y) & Edge(y, z)).named("PathRec")

  program = Program(rules=[base, rec])

  print("=== Rules ===")
  for r in program.rules:
    print(f"  {r.name}")

  print("\n=== Relations (auto-derived) ===")
  for r in program.relations:
    pragmas = []
    if r.print_size:
      pragmas.append("print_size=True")
    if r.input_file:
      pragmas.append(f"input_file={r.input_file!r}")
    pragma_str = ", " + ", ".join(pragmas) if pragmas else ""
    print(f"  {r.name}({r.arity}{pragma_str})")


if __name__ == "__main__":
  main()
