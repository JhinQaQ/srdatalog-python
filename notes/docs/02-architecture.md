# How I read this codebase

Notes on the structure of srdatalog-python as I'm figuring it out.  
The real docs are in `../docs/`. This is just my
mental map. I'll keep revising.

## My mental model

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


| Stage   | What it's for                                              | Where it lives                           |
| ------- | ---------------------------------------------------------- | ---------------------------------------- |
| DSL     | Your rules, as Python objects                              | `src/srdatalog/dsl.py`                   |
| HIR     | Cleaned up + planned Datalog (strata, semi-naive, indexes) | `src/srdatalog/hir/`                     |
| MIR     | Imperative-ish step plan (pipelines, fixpoints)            | `src/srdatalog/mir/`                     |
| Emit    | Print C++/CUDA source strings                              | `src/srdatalog/codegen/`, `codegen/jit/` |
| Compile | Run ninja + clang to build the `.so`                       | `codegen/jit/compiler_ninja.py`          |
| Load    | ctypes + extern "C" shim                                   | `codegen/jit/loader.py`                  |


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


| Name       | What I use it for                     |
| ---------- | ------------------------------------- |
| `Var`      | Logic variable: `x = Var("x")`        |
| `Relation` | A table: `Edge = Relation("Edge", 2)` |
| `Program`  | Wrap rules: `Program(rules=[...])`    |


The DSL also gives you operators (no import needed): `<=` for
"head ← body", `&` to AND body clauses, `~` for negation,
`.named("X")`, `.with_plan(var_order=...)`, `Filter(...)`, `Const(...)`.

### Compile


| Name             | What I think it does                           |
| ---------------- | ---------------------------------------------- |
| `compile_to_hir` | Program → HIR (stratify, plan, index)          |
| `compile_to_mir` | Program → MIR (step plan)                      |
| `build_project`  | Everything: lower + write `.cpp` files to disk |


### Build the .so


| Name                            | What I think it does                       |
| ------------------------------- | ------------------------------------------ |
| `CompilerConfig`                | Bundle of include paths / flags / libs     |
| `compile_jit_project`           | Run ninja+clang on the emitted `.cpp` tree |
| `CompileResult` / `BuildResult` | Output objects with stdout/stderr/paths    |
| `compile_cpp`, `link_shared`    | Lower-level building blocks                |


### Load + call


| Name             | What I think it does                           |
| ---------------- | ---------------------------------------------- |
| `EntryPoint`     | Says "this extern C symbol has this signature" |
| `JitRuntime`     | The loaded `CDLL` + your bound entry points    |
| `build_and_load` | One-shot: emit + compile + load                |


### Runtime detection (separate import)

`from srdatalog.runtime import runtime_include_paths, cuda_include_paths, runtime_defines, cuda_compile_flags, cuda_link_flags, cuda_libs, find_cuda_root`.

These tell `CompilerConfig` how to find CUDA, the runtime headers,
the vendor headers.

### The actual C ABI (lives in the compiled .so)

This is *not* Python — these are the C symbols you call via
ctypes after the `.so` is built. I keep needing to look these up:


| Symbol               | Signature                       | What it does                               |
| -------------------- | ------------------------------- | ------------------------------------------ |
| `srdatalog_init`     | `int()`                         | Init CUDA                                  |
| `srdatalog_load_csv` | `int(const char*, const char*)` | Load one relation from a CSV               |
| `srdatalog_load_all` | `int(const char*)`              | Load every `input_file=` relation in a dir |
| `srdatalog_run`      | `int(uint64_t)`                 | Run the fixpoint (0 = unlimited)           |
| `srdatalog_size`     | `uint64_t(const char*)`         | Read back the row count of a relation      |
| `srdatalog_shutdown` | `int()`                         | Free host state                            |


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
  - writing files to disk.
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

I don't have a solid database background, so I had to chase down what some  
of these mean. Quick notes here:

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
- **JIT**: "just-in-time", here it means "compile a specialized C++  
program just for this Datalog program, the first time you run it."  
Not interpretation at runtime.
- **Bundled runtime**: the generated C++ doesn't stand alone, it
includes headers from `src/srdatalog/runtime/generalized_datalog/`
and from `vendor/` (boost, highway, RMM, spdlog). Those headers
are where the actual GPU data structures live.

## What still confuses me

Todo list:

- I don't really know how to read the generated `jit_batch_N.cpp`
files yet. The runtime template machinery is heavy.
- I haven't figured out when the planner picks each `index_type`.
- I don't know what "work-stealing runner" means in this codebase.
- I haven't run any benchmark on a non-empty CSV yet — would like
to see actual non-zero result sizes.

I'll add answers here as I get them.

## Answers from Yihao (the original developer)

I asked the original developer about the items above. These are his
answers, paraphrased, plus my own notes so I can re-read them later
and still understand.

### Q: When does the planner pick each `index_type`?

Yihao's answer (paraphrased):

> It's done in an ad-hoc but complicated way. The planner scans every
> variable in a canonicalized order using the first atom of each body
> clause (the exact canonicalization has varied across versions —
> sometimes by appearance order of the variable, sometimes sorted).
> If a logical variable has the most "joined counts", it picks that
> variable first, then repeats until no variables are left, then moves
> to the next clause and does the same thing. But there are a lot of
> edge cases — let-bindings, conditions, and negated atoms are all
> handled differently.
>
> The reality is: I tried several ways to pick a "not bad" order that
> can also be canonicalized, so that when you test and tune you don't
> hit non-determinism (which is what makes slog unusable). That
> turned out to be very hard, so most of my queries end up using
> **manually ordered index selection**.
>
> "Manually" means: when you write a rule, you pick the variable
> order that makes sense to your intuition (based on your estimation —
> we don't have a query planner estimator). Then index selection with
> the customized order derives the correct index for each relation
> needed to run that variable order.

My notes for understanding this:

- "Joined count" = how often a variable appears across body atoms.
The planner uses that as a rough proxy for "this var is the join
key — bind it first."
- "Canonicalized order" matters because if the planner is
non-deterministic, the same program could compile to a different
plan on different runs, and benchmarks become noisy. He's trying
to keep the planner deterministic even if not perfect.
- The practical takeaway: **prefer to use `.with_plan(var_order=...)`
in real benchmarks** so you control the index selection instead of
relying on the heuristic.
- This is why almost every `examples/*.py` benchmark includes
`.with_plan(var_order=[...])` on important rules.

### Q: What is the "work-stealing runner" variant?

Yihao's answer:

> Skip this. It's a test to show in paper. Work stealing in an old
> paper is bad.

My notes:

- This was about the 2 out of 127 byte-match fixtures that don't
match the Nim reference. They depend on a "work-stealing" runner
variant.
- It is essentially a research checkpoint, not something I need to
care about as a user. I can ignore it.

### Q: How do I run benchmarks with real data so result sizes aren't 0?

Yihao's answer:

> Use https://huggingface.co/datasets/ysun67/srdatalog-benchmark

My notes:

- I already downloaded this dataset and got it to work — see
`notes/03-running-benchmarks.md` (or my own log) for the exact
commands I used.
- For `tc`, just point `--data` at any folder containing an
`Arc.csv`, e.g. `data/sg/usroad_small/`.
- For `doop`, point `--data` at one of the `data/doop/*/` folders
and pass `--meta` with the JSON. Note the upstream
`eclipse_interned/meta.json` was missing a few keys —
I had to regenerate it from `str2num.json`.

### Q: How do I read the generated `jit_batch_N.cpp` files?

Yihao's answer:

> I put a comment in the generated code showing where the C++ came
> from in the MIR. For the template-heavy code, you usually need to
> read it together with the C++ template functions in the
> `generalized_datalog` folder.
>
> The templates come from the fact that all relations are different,
> and a lot of details are pure compiler knowledge: the arity of the
> relation, its column types, its data structure, the hardware, and
> the CUDA kernel-launch arguments. C++ templates are what let us
> simplify all of this so the codegen layer doesn't have to rewrite
> a different C++ program for every relation shape.

My notes for understanding this:

- "Compiler knowledge" he means: things the Python compiler knows but
that C++ would otherwise need a separate version per relation:
arity (number of columns), column types, index layout, kernel
launch shape.
- Templates push that variation into the C++ type system instead of
the codegen. So instead of emitting a custom `Path_join_Edge_kernel`
for each rule, codegen emits something like
`Join<PathLayout, EdgeLayout>::run(...)` and the C++ template
machinery in `generalized_datalog/` figures out the concrete code.
- The comments he mentions show up at the top of generated blocks in
`jit_batch_N.cpp` — they pin a chunk of C++ back to its MIR step.
The right way to read these files is:
1. Find the comment that names a MIR step.
2. Cross-reference that step in `mir/types.py` /
`codegen/jit/orchestrator_jit.py`.
3. For any template like `JitRunner<...>` or `Index<...>`, open the
matching header under
`src/srdatalog/runtime/generalized_datalog/` to see what the
template actually does.
- TL;DR: the generated `.cpp` files are not meant to be read by
themselves. They are a *thin specialized layer* on top of the
templates in the runtime folder.