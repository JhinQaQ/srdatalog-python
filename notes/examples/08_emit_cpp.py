"""08_emit_cpp.py — emit the C++/CUDA source tree to disk.

What this shows:
  - `build_project(program, project_name="...", cache_base="./build")`
    runs the full Python pipeline (DSL -> HIR -> MIR -> codegen) and
    writes the generated `.cpp` files into a cache directory.
  - No compiler is invoked. This is safe to run without clang/CUDA.

  After running, look under `./build/jit/SmallTC_DB_<hash>/` — you
  will find `main.cpp`, one or more `jit_batch_*.cpp` files, and
  the schema header.

Run:
  uv run python notes/examples/08_emit_cpp.py
"""

from __future__ import annotations

import pathlib

from srdatalog import Program, Relation, Var, build_project


def main() -> None:
  x, y, z = Var("x"), Var("y"), Var("z")
  Edge = Relation("Edge", 2, input_file="Edge.csv")
  PathRel = Relation("Path", 2, print_size=True)

  program = Program(rules=[
    (PathRel(x, y) <= Edge(x, y)).named("PathBase"),
    (PathRel(x, z) <= PathRel(x, y) & Edge(y, z)).named("PathRec"),
  ])

  result = build_project(program, project_name="SmallTC", cache_base="./build")

  print("=== Emitted layout (JitProjectLayout TypedDict) ===")
  for key, val in result.items():
    if isinstance(val, list):
      print(f"  {key:18s} = [{len(val)} entries]")
      for item in val:
        print(f"    - {item}")
    else:
      print(f"  {key:18s} = {val}")

  out_dir = pathlib.Path(result["dir"])
  print(f"\nFiles under {out_dir}:")
  if out_dir.exists():
    for child in sorted(out_dir.iterdir()):
      print(f"  {child.name}")

  print(
    "\nThis only emitted source. To actually compile it, see "
    "`examples/run_benchmark.py` or call `compile_jit_project` from "
    "srdatalog (requires clang++ >= 20 and CUDA 12.x)."
  )


if __name__ == "__main__":
  main()
