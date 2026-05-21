# How to Run This Project

These are personal notes on installing and running `srdatalog-python` v0.1.0.

The project is a **Python frontend for a Datalog engine that emits C++/CUDA**.
Running it means two different things depending on what you want:

1. **Python-only**: import the DSL, build a `Program`, lower it through HIR/MIR,
   emit the C++/CUDA source files to disk. No GPU needed. Works on any box.
2. **Full JIT**: also compile those generated `.cpp` files with `clang++` + CUDA,
   load the resulting `.so` with `ctypes`, and actually run the Datalog program.
   Needs a real toolchain on the machine.

The Python-only path is enough to read code, run unit tests, and explore HIR/MIR.

---

## 1. Prerequisites

### Python side (required for everything)

- Python 3.10+ (this checkout was tested with 3.13 via `uv`)
- `uv` package manager (`/snap/bin/uv` on this box)

### Native side (only for full JIT compile + run)

- `clang++` version **>= 20** (NOT gcc, NOT nvcc).
- **CUDA 12.x** toolkit (CUDA 13 dropped a header the pinned RMM still needs).
- `libboost_container` on the link path — e.g. `apt install libboost-container-dev`.
- Optional: `ccache` on `$PATH` — auto-detected by ninja, huge warm-build win.
- Optional: an NVIDIA GPU if you want to actually run kernels, not just compile.

If you only want to explore the codebase, skip the native side for now.

---

## 2. One-time setup

From the repo root (this folder, `0_1/`):

```bash
# Create .venv and install Python deps + dev tools (pytest, ruff, ...).
uv sync --group dev

# Fetch vendored C++ headers (boost / highway / RMM / spdlog) into vendor/.
# Only matters when you actually compile generated code. Safe to run anyway.
uv run python scripts/populate_vendor.py

# Editable install of the package itself so `import srdatalog` works.
uv pip install -e .
```

Verify:

```bash
uv run python -c "import srdatalog; print(srdatalog.__version__)"
# expected: 0.1.0
```

Note for this checkout: `pyproject.toml` was patched to add `cffi` to
`dependencies` (the FFI wrapper imports it). If you re-clone the upstream
tag, you may hit `ModuleNotFoundError: cffi` until that fix is in.

---

## 3. Run the tests (Python-only path, no GPU)

```bash
uv run pytest -q
```

This runs the unit tests under `tests/` and exercises the DSL, HIR passes,
MIR lowering, and codegen — all without invoking `clang++`.

To run a single test file:

```bash
uv run pytest tests/test_generate_program.py -q
```

---

## 4. Build a program without compiling (safe, fast)

You can build a `Program`, lower it, and emit the `.cpp` tree to disk
without invoking clang. Useful for reading the generated C++.

```python
# scratch.py — run with: uv run python scratch.py
from srdatalog import Var, Relation, Program, build_project

x, y, z = Var("x"), Var("y"), Var("z")
Edge = Relation("Edge", 2, input_file="Edge.csv")
Path = Relation("Path", 2, print_size=True)

prog = Program(rules=[
    (Path(x, y) <= Edge(x, y)).named("TCBase"),
    (Path(x, z) <= Path(x, y) & Edge(y, z)).named("TCRec"),
])

project = build_project(prog, project_name="TC", cache_base="./build")
print(project)  # paths to generated main.cpp + jit_batch_*.cpp
```

After this, look under `./build/jit/TC_DB_<hash>/` — that is the
generated C++/CUDA tree. Open `main.cpp` and the `jit_batch_*.cpp`
files to see what was emitted.

---

## 5. Full JIT compile + run (needs clang-20 + CUDA + boost)

If you have the native toolchain installed, the easiest end-to-end
test is the bundled benchmark runner:

```bash
# Synthetic triangle benchmark — no input CSV needed:
uv run python examples/run_benchmark.py triangle

# Transitive closure on real CSV data:
uv run python examples/run_benchmark.py tc --data /path/to/edges_dir

# Limit fixpoint iterations for a quick sanity check:
uv run python examples/run_benchmark.py galen --data /path/to/data --max-iter 3
```

Each invocation prints one line per phase (DSL build / emit / compile /
load / run) with timings, so you can see exactly where time is going.

To do the same thing manually in Python, see the quickstart in
`README.md` — it uses `build_project` + `compile_jit_project` + `ctypes.CDLL`.

---

## 6. Useful environment toggles

| Variable | Meaning |
|---|---|
| `SRDATALOG_JIT_NO_CCACHE=1` | Disable ccache even if it is on PATH. |
| `SRDATALOG_JIT_NO_NINJA=1` | Fall back to the ThreadPoolExecutor compiler (no ninja). |
| `CXX` | Override which clang++ binary is used. |
| `CUDA_HOME` | Override CUDA detection. |

---

## 7. What "running" really means here

There is no long-running server, no daemon. A "run" is just:

1. Python builds a `Program` (your rules).
2. Python lowers it and emits C++/CUDA source files into a cache dir.
3. ninja + clang compile those files into a `.so`.
4. Python `ctypes.CDLL`s the `.so` and calls `srdatalog_init`,
   `srdatalog_load_all`, `srdatalog_run`, `srdatalog_size`,
   `srdatalog_shutdown`.

The Python process is the **driver**; the actual Datalog evaluation
runs in compiled native code (CPU host + CUDA device).
