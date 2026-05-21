# How I read this codebase

Notes on the structure of srdatalog-python as I'm figuring it out.
Not authoritative — the real docs are in `../docs/`. This is just my
mental map. I'll keep revising.

## My one-line mental model

It's a compiler. The input is a Datalog-style program written in
Python. The output is C++/CUDA source code that uses a bundled GPU
runtime. Then clang+ninja turn that source into a `.so`, and Python
loads it with ctypes and calls into it.

So Python is the **frontend + driver**, not the engine.

This was confusing to me at first because the name has "Python" in
it. I kept expecting Python to do the evaluation. It doesn't —
Python builds an AST, lowers it through two IRs, prints C++ to
disk, asks clang to compile it, then opens the result and calls it.

## The pipeline

```
Python DSL  →  HIR  →  MIR  →  C++/CUDA source  →  .so  →  ctypes calls
  (rules)      (analyzed     (step-by-step       (clang+ninja
                Datalog)      execution plan)     build it)
```

| Stage | What it's for | Where it lives |
|---|---|---|
| DSL | Your rules, as Python objects | `src/srdatalog/dsl.py` |
| HIR | Cleaned up + planned Datalog (strata, semi-naive, indexes) | `src/srdatalog/hir/` |
| MIR | Imperative-ish step plan (pipelines, fixpoints) | `src/srdatalog/mir/` |
| Emit | Print C++/CUDA source strings | `src/srdatalog/codegen/`, `codegen/jit/` |
| Compile | Run ninja + clang to build the `.so` | `codegen/jit/compiler_ninja.py` |
| Load | ctypes + extern "C" shim | `codegen/jit/loader.py` |

The cheat I use when I'm confused about what a file is for: ask
"which arrow is this?" Usually it's one of those six.

## Folder map I built for myself

```
0_1/
├── src/srdatalog/      # the library
│   ├── dsl.py             # the DSL surface (Var, Relation, Program, rules)
│   ├── hir/               # DSL → HIR passes
│   ├── mir/               # HIR → MIR + MIR passes
│   ├── codegen/           # MIR → C++/CUDA strings
│   │   ├── jit/           # JIT-specific: cache, compiler, loader, runners
│   │   ├── batchfile.py
│   │   ├── helpers.py
│   │   └── schema.py
│   ├── runtime/           # detect CUDA, list include paths, vendor headers
│   ├── pipeline.py        # compile_program: DSL → HIR → MIR → emit strings
│   ├── build.py           # build_project: pipeline + write files to disk
│   ├── ffi/               # cffi wrapper (older non-JIT path)
│   ├── srdatalog_program.py  # older non-JIT entry point
│   └── viz/               # optional visualization
├── examples/           # 17 benchmarks + run_benchmark.py
├── tests/              # pytest
├── tools/              # nim_to_dsl.py + friends
├── docs/               # official markdown docs
├── scripts/            # populate_vendor.py + build hooks
└── docker/             # CUDA + clang-20 image (haven't tried this)
```

## Public API (what `from srdatalog import ...` gives you)

I cross-referenced this with `src/srdatalog/__init__.py`. Grouped
by what I think each thing is for:

### Write the DSL

| Name | What I use it for |
|---|---|
| `Var` | Logic variable: `x = Var("x")` |
| `Relation` | A table: `Edge = Relation("Edge", 2)` |
| `Program` | Wrap rules: `Program(rules=[...])` |

The DSL also gives you operators (no import needed): `<=` for
"head ← body", `&` to AND body clauses, `~` for negation,
`.named("X")`, `.with_plan(var_order=...)`, `Filter(...)`, `Const(...)`.

### Compile

| Name | What I think it does |
|---|---|
| `compile_to_hir` | Program → HIR (stratify, plan, index) |
| `compile_to_mir` | Program → MIR (step plan) |
| `build_project` | Everything: lower + write `.cpp` files to disk |

### Build the .so

| Name | What I think it does |
|---|---|
| `CompilerConfig` | Bundle of include paths / flags / libs |
| `compile_jit_project` | Run ninja+clang on the emitted `.cpp` tree |
| `CompileResult` / `BuildResult` | Output objects with stdout/stderr/paths |
| `compile_cpp`, `link_shared` | Lower-level building blocks |

### Load + call

| Name | What I think it does |
|---|---|
| `EntryPoint` | Says "this extern C symbol has this signature" |
| `JitRuntime` | The loaded `CDLL` + your bound entry points |
| `build_and_load` | One-shot: emit + compile + load |

### Runtime detection (separate import)

`from srdatalog.runtime import runtime_include_paths,
cuda_include_paths, runtime_defines, cuda_compile_flags,
cuda_link_flags, cuda_libs, find_cuda_root`.

These tell `CompilerConfig` how to find CUDA, the runtime headers,
the vendor headers.

### The actual C ABI (lives in the compiled .so)

This is *not* Python — these are the C symbols you call via
ctypes after the `.so` is built. I keep needing to look these up:

| Symbol | Signature | What it does |
|---|---|---|
| `srdatalog_init` | `int()` | Init CUDA |
| `srdatalog_load_csv` | `int(const char*, const char*)` | Load one relation from a CSV |
| `srdatalog_load_all` | `int(const char*)` | Load every `input_file=` relation in a dir |
| `srdatalog_run` | `int(uint64_t)` | Run the fixpoint (0 = unlimited) |
| `srdatalog_size` | `uint64_t(const char*)` | Read back the row count of a relation |
| `srdatalog_shutdown` | `int()` | Free host state |

## My suggested reading path

Order that worked for me:

1. README quickstart in the project root. Just paste-and-stare.
2. `examples/tc.py` — what a real program looks like.
3. `src/srdatalog/dsl.py` — how `<=`, `&`, `~`, `Filter`, `Const`,
   `.named`, `.with_plan` are implemented. The docstring at the top
   is a great mini-tutorial.
4. `src/srdatalog/pipeline.py` → the `compile_program` function.
   It's the spine. It calls `compile_to_hir`, then `compile_to_mir`,
   then each emitter in turn.
5. `src/srdatalog/build.py` → `build_project` is just `compile_program`
   + writing files to disk.
6. `examples/run_benchmark.py` — full end-to-end: program → emit
   → compile → load → run.

Then to go deeper (haven't fully done this yet):

- `hir/__init__.py` and the per-pass files (stratify, semi_naive,
  plan, index, lower).
- `mir/types.py`, `mir/commands.py`, `mir/passes.py`.
- `codegen/jit/complete_runner.py` and `main_file.py` (this is where
  C++ strings actually get printed).
- `codegen/jit/compiler_ninja.py` for how the build is orchestrated.

## Concepts I had to look up

I don't have a database background, so I had to chase down what some
of these mean. Quick notes for future-me:

- **Relation**: a named table with fixed arity. `Edge(x, y)` is a
  table with two columns.
- **Rule**: "for every binding where the body holds, add this tuple
  to the head." So `Path(x, z) <= Path(x, y) & Edge(y, z)` is "if
  there's already a path x→y and an edge y→z, then also a path x→z."
- **Fixpoint**: keep applying the rules until nothing new is added.
  Recursive rules need this.
- **Stratification**: when negation is involved, you have to fully
  finish computing one group of relations before another can use
  their negation. HIR groups rules into "strata" so this happens
  cleanly.
- **Semi-naive evaluation**: instead of re-doing the full join every
  iteration, you only join against the *new* tuples from the last
  iteration. HIR generates "variants" of each recursive rule, one
  per "delta position."
- **JIT**: "just-in-time" — here it means "compile a specialized C++
  program just for this Datalog program, the first time you run it."
  Not interpretation at runtime.
- **Bundled runtime**: the generated C++ doesn't stand alone, it
  includes headers from `src/srdatalog/runtime/generalized_datalog/`
  and from `vendor/` (boost, highway, RMM, spdlog). Those headers
  are where the actual GPU data structures live.

## What still confuses me

Honest list:

- I don't really know how to read the generated `jit_batch_N.cpp`
  files yet. The runtime template machinery is heavy.
- I haven't figured out when the planner picks each `index_type`.
- I don't know what "work-stealing runner" means in this codebase.
- I haven't run any benchmark on a non-empty CSV yet — would like
  to see actual non-zero result sizes.

I'll add answers here as I get them.
