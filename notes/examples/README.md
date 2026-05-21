# Walkthrough Examples

These small scripts go from "just inspect a `Program`" up to "emit C++
files to disk." They are written for *understanding the codebase*, not
for benchmarking. They all run on CPU-only Python (no clang, no CUDA
needed) unless explicitly noted.

Run any of them with:

```bash
cd /home/jinyang/Code/srdatalog/0_1
uv run python notes/examples/01_hello.py
```

## Files

| File | Feature |
|---|---|
| `01_hello.py` | Minimum viable `Program` + how to inspect it |
| `02_transitive_closure.py` | Recursion: the classic Datalog example |
| `03_filters_and_constants.py` | `Filter(...)` and integer constants in atoms |
| `04_negation.py` | `~Atom(...)` to express "and NOT" |
| `05_multi_head_and_named.py` | `(A | B) <= body`, `.named(...)` |
| `06_planning.py` | `.with_plan(var_order=...)` to guide the join planner |
| `07_inspect_hir_mir.py` | Run `compile_to_hir` / `compile_to_mir` and look at the IRs |
| `08_emit_cpp.py` | `build_project(...)` — write the C++/CUDA tree to disk |

No GPU is needed for files 1–8. File 8 only **emits** the source; it does
not compile. To actually compile and run, see `notes/01-running.md`
(`examples/run_benchmark.py`).
