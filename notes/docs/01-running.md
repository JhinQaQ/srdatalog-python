# How I run this project

Just my notes on how I got srdatalog-python v0.1.0 running on my own
box. Not a real install guide — the official one is in `../README.md`
and `../docs/getting_started.md`. I'm writing this down so I don't
forget the bits that tripped me up.

## What "running" actually means here

This took me a minute to wrap my head around. There is no daemon, no
server, no REPL. "Running" the project is really two different things:

1. **Python only**: import the DSL, build a `Program`, run the
  compiler frontend (HIR/MIR), and optionally write generated C++
   files to disk. No clang, no GPU, no CUDA needed. This is what I
   do 90% of the time when I'm just reading the codebase.
2. **Full pipeline**: also compile those generated `.cpp` files with
  clang + CUDA, load the resulting `.so` with ctypes, actually
   execute. Needs a real toolchain.

I mostly stick to #1 while I'm still figuring things out.

## What you need

For the Python-only path:

- Python 3.10+ (I'm using 3.13 via uv on this box).
- `uv` — `/snap/bin/uv` here.

For the full pipeline (which I haven't been doing much yet):

- `clang++` 20+ (not gcc, not nvcc — the docs are very clear about this).
- CUDA 12.x (CUDA 13 dropped a header the pinned RMM still needs).
- `libboost_container` (`apt install libboost-container-dev`).
- Optional but recommended: `ccache` on PATH.
- An NVIDIA GPU if you actually want to run the kernels, not just
compile them.

## Setup I did once

From the project root (`0_1/`):

```bash
uv sync --group dev
uv run python scripts/populate_vendor.py
uv pip install -e .
```

What each one does, as far as I can tell:

- `uv sync --group dev` creates `.venv` and installs Python deps
  - dev tools.
- `populate_vendor.py` downloads C++ headers (boost, highway, RMM,
spdlog) into `vendor/`. Only matters when you actually compile.
- `uv pip install -e .` editable installs the package itself so
`import srdatalog` works from any cwd.

Sanity check:

```bash
uv run python -c "import srdatalog; print(srdatalog.__version__)"
# expected: 0.1.0
```

> small fix: out of the box, `import srdatalog` fails with
> `ModuleNotFoundError: cffi`. The fix is to add `cffi>=1.15` to
> `dependencies` in `pyproject.toml` (the FFI wrapper imports it but
> v0.1.0 forgot to declare it). I already made that fix in my
> checkout.

## Things I've actually run

### Run the tests

```bash
uv run pytest -q
```

This is purely Python — no clang, safe to run anywhere.

### Run one of my walkthrough scripts

```bash
uv run python notes/examples/01_hello.py
uv run python notes/examples/07_inspect_hir_mir.py
uv run python notes/examples/08_emit_cpp.py
```

These are in `notes/examples/` — see the README in there for what
each one shows.

### Run a real benchmark (full pipeline)

I tried this once on a box with CUDA + clang-20 + a GPU:

```bash
uv run python examples/run_benchmark.py triangle
```

That actually went through DSL → emit → ninja compile → load → run
and printed result sizes. First time was slow (~34s compile) because
nothing was cached. Result sizes were all 0 because there was no
input data, but that's expected for `triangle` since none of its
relations declared `input_file=...`.

To run something on real input data:

```bash
uv run python examples/run_benchmark.py tc --data /path/to/folder_with_csvs
```

The script prints per-phase timings, which is nice for seeing where
time goes.

## Environment variables


| Variable                    | What it does                                      |
| --------------------------- | ------------------------------------------------- |
| `SRDATALOG_JIT_NO_CCACHE=1` | Disable ccache even if installed.                 |
| `SRDATALOG_JIT_NO_NINJA=1`  | Fall back to ThreadPoolExecutor instead of ninja. |
| `CXX`                       | Override which clang++ binary is used.            |
| `CUDA_HOME`                 | Override CUDA toolkit detection.                  |


I haven't needed any of these yet but writing them down so I know
they exist.