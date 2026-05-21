# Notes — srdatalog-python v0.1.0

Personal notes on this checkout of `srdatalog-python` v0.1.0.
The upstream docs live under `../docs/` and at
<https://harp-lab.github.io/srdatalog-python/>; these notes are a
shorter, plain-English on-ramp.

Read in this order:

1. **[`01-running.md`](01-running.md)** — how to install and run the
   project (Python-only path and full JIT path).
2. **[`02-architecture.md`](02-architecture.md)** — how to read the
   codebase: pipeline, folder map, public API, and key concepts.

One-sentence summary:

> srdatalog-python is a Python compiler that takes Datalog-like rules
> and emits C++/CUDA code, compiles it with clang+ninja, and lets you
> run the result from Python via `ctypes`.
