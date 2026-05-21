"""04_negation.py — stratified negation with `~`.

What this shows:
  - `~Edge(x, y)` in a rule body means "there is NO Edge(x, y)".
  - Adding negation forces HIR's stratification: rules with negative
    dependencies on a relation must be in a later stratum than the
    rules that define that relation.

  Logical meaning:
    Person(p)         :- Member(p, _team)
    Lonely(p)         :- Person(p), ~HasFriend(p, _someone)

  ("Lonely" = a Person who has no friend.)

Run:
  uv run python notes/examples/04_negation.py
"""

from __future__ import annotations

from srdatalog import Program, Relation, Var


def main() -> None:
  p, team, someone = Var("p"), Var("team"), Var("someone")

  Member = Relation("Member", 2)
  HasFriend = Relation("HasFriend", 2)
  Person = Relation("Person", 1)
  Lonely = Relation("Lonely", 1)

  person_rule = (Person(p) <= Member(p, team)).named("PersonFromMember")
  lonely_rule = (Lonely(p) <= Person(p) & ~HasFriend(p, someone)).named("Lonely")

  program = Program(rules=[person_rule, lonely_rule])

  print("=== Rules ===")
  for r in program.rules:
    has_neg = any(type(c).__name__ == "Negation" for c in r.body)
    print(f"  {r.name}  has_negation={has_neg}")

  print(
    "\nDuring HIR compile, the stratifier will put `PersonFromMember` "
    "in an earlier stratum than `Lonely`, because `Lonely` negatively "
    "depends on `HasFriend` and positively depends on `Person`."
  )


if __name__ == "__main__":
  main()
