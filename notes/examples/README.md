# My walkthrough scripts

Small Python files I wrote while learning the DSL. They go from
"just inspect a Program" to "actually emit C++ files." All of them
run on plain Python — no clang, no CUDA, no GPU.

Run any of them like:

```bash
cd /home/jinyang/Code/srdatalog/0_1
uv run python notes/examples/01_hello.py
```

## What each one is for

| File | What I'm trying to learn |
|---|---|
| `01_hello.py` | Smallest possible `Program`. Just to see the shape. |
| `02_transitive_closure.py` | Recursion. The classic Datalog example. |
| `03_filters_and_constants.py` | How filters and integer constants look. |
| `04_negation.py` | `~Atom(...)` and why it adds another stratum. |
| `05_multi_head_and_named.py` | Multi-head rules and naming. |
| `06_planning.py` | Hinting the join planner with `var_order`. |
| `07_inspect_hir_mir.py` | Calling `compile_to_hir` / `compile_to_mir` directly and looking at the IRs. |
| `08_emit_cpp.py` | `build_project(...)` to actually write C++/CUDA files to `./build/jit/...`. |

## My suggested order

1. **Run 01 and 02 first.** Get a feel for what a `Program` looks like.
2. **Run 07.** Looking at strata + MIR steps was the moment HIR/MIR
   stopped being abstract for me.
3. **Run 08, then open the generated files.** The directory it prints
   has `main.cpp` and `jit_batch_0.cpp`. Reading those side-by-side
   with the original rules in Python is the best way I've found to
   understand what the codegen is actually doing.

## Caveat

These are written for understanding, not for benchmarking. The rules
are small and the input is empty. To actually run with input data and
GPU execution, use `examples/run_benchmark.py` instead.
