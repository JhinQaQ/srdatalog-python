# How to Read This Project — Architecture and API

These are personal notes for reading `srdatalog-python` without
getting lost. Read `01-running.md` first if you have not set up
the project yet.

---

## 1. One-sentence summary

`srdatalog-python` is a **compiler written in Python**. The input
is a small **Datalog-style DSL** (relations + rules). The output
is **C++/CUDA source code** that uses a bundled GPU Datalog runtime,
compiled into a `.so` and called from Python via `ctypes`.

Python = compiler frontend + driver.
Native code = the real engine.

---

## 2. The pipeline

The whole project is one linear pipeline:

```
Python DSL  →  HIR  →  MIR  →  C++/CUDA source  →  .so  →  ctypes calls
   (your        (analyzed     (step-by-step      (compiled
    rules)       Datalog)      execution plan)    runtime)
```

| Stage   | What it represents                                       | Where in code                                       |
|---------|----------------------------------------------------------|-----------------------------------------------------|
| DSL     | Your Python `Program` with rules                         | `src/srdatalog/dsl.py`                              |
| HIR     | Stratified, semi-naive Datalog with join plans + indexes | `src/srdatalog/hir/`                                |
| MIR     | Ordered execution steps (pipelines, fixpoints)           | `src/srdatalog/mir/`                                |
| Emit    | Strings of generated C++/CUDA                            | `src/srdatalog/codegen/`, `src/srdatalog/codegen/jit/` |
| Compile | ninja + clang++ producing a `.so`                        | `src/srdatalog/codegen/jit/compiler_ninja.py`       |
| Load    | `ctypes.CDLL` + `extern "C"` shim                        | `src/srdatalog/codegen/jit/loader.py`               |

Two helpful mental shortcuts:
- **HIR = "what program (logic)"** — still relational, still Datalog-shaped.
- **MIR = "how to execute it"** — closer to imperative code.

---

## 3. Top-level folder map

```
0_1/
├── src/srdatalog/      # The library itself
│   ├── dsl.py             # User-facing DSL (Var, Relation, Program, rules)
│   ├── hir/               # DSL → HIR passes (stratify, plan, index)
│   ├── mir/               # HIR → MIR + MIR passes
│   ├── codegen/           # MIR → C++/CUDA strings
│   │   ├── jit/           # JIT-specific emitters + ninja driver + loader
│   │   ├── batchfile.py
│   │   ├── helpers.py
│   │   └── schema.py
│   ├── runtime/           # Auto-detect CUDA, list include paths, vendor headers
│   ├── pipeline.py        # `compile_program`: DSL → HIR → MIR → strings
│   ├── build.py           # `build_project`: pipeline + write files to disk
│   ├── ffi/               # cffi wrapper (used by the older non-JIT path)
│   ├── srdatalog_program.py  # Older non-JIT entry point
│   └── viz/               # Optional visualization helpers
├── examples/           # 17 benchmarks + run_benchmark.py driver
├── tests/              # pytest suite
├── tools/              # nim_to_dsl.py and friends
├── docs/               # Markdown docs (architecture, getting_started, ...)
├── scripts/            # populate_vendor.py + build hooks
└── docker/             # Self-contained CUDA + clang-20 image
```

---

## 4. Public API (what gets exported)

From `src/srdatalog/__init__.py`. These are the names you `from srdatalog import ...`:

### DSL surface

| Name       | Purpose                                                      |
|------------|--------------------------------------------------------------|
| `Var`      | A logic variable, e.g. `x = Var("x")`                        |
| `Relation` | A named table with arity, e.g. `Edge = Relation("Edge", 2)`  |
| `Program`  | Top-level container: `Program(rules=[...])`                  |

Plus operators on those objects:
- `Head(x, y) <= Body1(x, z) & Body2(z, y)` — builds a `Rule`
- `~Atom(...)` — negation
- `Filter((x,), "return x > 0;")` — inline C++ filter on variables
- `.named("RuleName")`, `.with_plan(var_order=[...])` — rule annotations

### Compile pipeline

| Function           | Purpose                                           |
|--------------------|---------------------------------------------------|
| `compile_to_hir`   | DSL `Program` → HIR (stratified, planned)         |
| `compile_to_mir`   | DSL `Program` → MIR (step plan)                   |
| `build_project`    | One-shot: DSL → HIR → MIR → write `.cpp` tree     |

### Code-emit building blocks (rarely needed directly)

| Function                          | Purpose                                  |
|-----------------------------------|------------------------------------------|
| `gen_complete_runner`             | Emit `JitRunner_<rule>` C++ struct       |
| `gen_step_body`                   | Emit one `step_N` body                   |
| `gen_main_file_content`           | Compose `main.cpp`                       |
| `gen_schema_definitions_for_batch`| Emit schema section for a batch file     |
| `gen_db_type_alias_for_batch`     | Emit `using <Project>_DB_Blueprint = ...` |
| `write_jit_project`               | Write the emitted strings to disk        |

### Compile / link (ninja + clang)

| Name                  | Purpose                                                  |
|-----------------------|----------------------------------------------------------|
| `CompilerConfig`      | Includes / defines / cxx_flags / link_flags / libs       |
| `compile_cpp`         | Compile one `.cpp` → `.o`                                |
| `link_shared`         | Link `.o` files into a `.so`                             |
| `compile_jit_project` | One-shot: emit `build.ninja`, run ninja, return result   |
| `CompileResult` / `BuildResult` | Result objects with stdout/stderr/paths        |

### Load + call (ctypes)

| Name                | Purpose                                                       |
|---------------------|---------------------------------------------------------------|
| `EntryPoint`        | `extern "C"` symbol descriptor (argtypes, restype)            |
| `JitRuntime`        | Holds the loaded `CDLL` + bound entry points                  |
| `build_and_load`    | One-shot: emit + compile + load + bind entry points           |
| `gen_runtime_shim_template` | Helper for emitting custom shims                      |

### Runtime detection (`from srdatalog.runtime import ...`)

| Function                | Purpose                                       |
|-------------------------|-----------------------------------------------|
| `runtime_include_paths` | Where bundled runtime + vendor headers live   |
| `cuda_include_paths`    | Auto-detected CUDA include dirs               |
| `runtime_defines`       | `-D...` macros the runtime expects            |
| `cuda_compile_flags`    | `-x cuda --cuda-path=...` etc.                |
| `cuda_link_flags`       | `-L...` etc.                                  |
| `cuda_libs`             | `["cudart", "cuda", ...]`                     |
| `find_cuda_root`        | Locate CUDA 12.x toolkit                      |

### Generated C ABI (the symbols you call from `ctypes`)

These are *not* Python — they live in the compiled `.so`:

| Symbol               | Signature                                  | Meaning                                            |
|----------------------|--------------------------------------------|----------------------------------------------------|
| `srdatalog_init`     | `int()`                                    | `init_cuda()`                                      |
| `srdatalog_load_csv` | `int(const char*, const char*)`            | Load one relation from a CSV file                  |
| `srdatalog_load_all` | `int(const char*)`                         | Walk every `input_file` relation in one dir        |
| `srdatalog_run`      | `int(uint64_t max_iters)`                  | Run the fixpoint; `0` = unlimited                  |
| `srdatalog_size`     | `uint64_t(const char*)`                    | Read back the size of a relation                   |
| `srdatalog_shutdown` | `int()`                                    | Free host state                                    |

---

## 5. Reading order (what to open first)

A reasonable horizontal slice:

1. **`README.md` quickstart** — paste-able TC example.
2. **`examples/tc.py`** — what a real program looks like.
3. **`src/srdatalog/dsl.py`** — how `Var`, `Relation`, `<=`, `&`, `~`,
   `Filter`, `.named`, `.with_plan` are implemented.
4. **`src/srdatalog/pipeline.py`** — `compile_program` is the heart of
   the compiler: it calls `compile_to_hir`, `compile_to_mir`, then
   each emitter.
5. **`src/srdatalog/build.py`** — `build_project` is the thin wrapper
   that adds disk I/O on top of `compile_program`.
6. **`examples/run_benchmark.py`** — end-to-end driver: program → emit
   → ninja compile → ctypes load → run.

Then, if you want to dig deeper:

- **HIR passes**: `src/srdatalog/hir/__init__.py` + `hir/*.py`
  (stratify, semi_naive, plan, index, lower, split).
- **MIR types and passes**: `src/srdatalog/mir/types.py`, `mir/passes.py`,
  `mir/commands.py`, `mir/runner.py`.
- **C++ emitters**: `src/srdatalog/codegen/jit/complete_runner.py`,
  `codegen/jit/main_file.py`, `codegen/jit/orchestrator_jit.py`,
  `codegen/jit/pipeline.py`, `codegen/jit/kernel_functor.py`.
- **Build orchestration**: `codegen/jit/compiler_ninja.py`,
  `codegen/jit/compiler.py`, `codegen/jit/cache.py`.
- **Loading**: `codegen/jit/loader.py`.

---

## 6. Key concepts you will hit

### Relations and rules

A `Relation` is a named table with a fixed arity. A `Rule` says:
"these new tuples should appear in the head relation when these
body atoms are simultaneously true."

```python
(Path(x, z) <= Path(x, y) & Edge(y, z)).named("TCRec")
```

is the Datalog rule `Path(x, z) :- Path(x, y), Edge(y, z)`.

### Stratification

Rules with negation cannot be evaluated in one big loop. The HIR
stage groups rules into **strata** so that each stratum can be
evaluated to a fixpoint before the next one starts.

### Semi-naive evaluation

Instead of recomputing all rules over the full relation on every
iteration, the engine tracks **deltas** (rows added in the last
iteration) and only joins those against existing rows. The HIR
emits one **variant** of each recursive rule per "delta position."

### Join planning

For each rule, HIR picks:
- a **variable order** (the join order),
- a **clause order** (which body atom to scan first),
- an **access pattern** per body atom (which columns are bound vs free),
- indexes on each relation that make those patterns cheap.

`.with_plan(var_order=[...])` lets you override the planner.

### Fixpoint

Recursive rules keep firing until no new tuples appear. That outer
loop is generated as a `FixpointPlan` in MIR and as a `while` loop
in C++.

### JIT

"JIT" here means "compile this specific program just-in-time when
the user asks to run it" — not "interpret Python at runtime." A
fresh `.so` is built for each unique program shape and cached on
disk.

### Bundled runtime

The generated C++ files don't stand alone — they `#include` headers
from `src/srdatalog/runtime/generalized_datalog/` (this project's
runtime) and from `vendor/` (Boost, Highway, RMM, spdlog). Those
headers implement the actual GPU data structures, kernels, and
fixpoint loop.

---

## 7. Where examples come from

The 17 files in `examples/` were **auto-generated** from upstream
Nim sources by `tools/nim_to_dsl.py`. Each one defines:

- A few `Relation(...)` declarations at module level.
- A `build_<schema>_program()` function that returns a `Program`.

`examples/run_benchmark.py` knows that convention and uses it to
drive any of them end-to-end.

---

## 8. Status — what works and what does not

From `README.md`'s "Status & roadmap":

Working:
- DSL, HIR, MIR, JIT codegen.
- 125 / 127 runner fixtures byte-match the upstream Nim reference.
- ninja + ccache compile orchestrator.
- ctypes loader with the 5–6 entry-point shim.
- Relation pragmas: `input_file=`, `print_size=`, `index_type=`.
- `dataset_const` resolution.
- Nim → Python translator.
- All 17 canonical benchmarks runnable via `examples/run_benchmark.py`.

Not yet:
- Work-stealing runner variant (blocks the last 2 runner fixtures).
- Precompiled headers (PCH) — disabled due to a clang-20 ODR bug.
- Pre-built native runtime — users still need clang-20 + CUDA 12 +
  libboost_container locally.

---

## 9. TL;DR for newcomers

If you just want a working mental model:

> You write Datalog-like rules in Python. The library lowers them
> through two IRs (HIR, MIR), prints C++/CUDA source files that use
> a bundled GPU runtime, compiles those with clang+ninja into a `.so`,
> and lets you load and call it from Python with `ctypes`.

Everything else is implementation detail of one of those six arrows.
