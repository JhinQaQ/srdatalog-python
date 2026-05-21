# My notes on srdatalog-python v0.1.0

These are my personal notes while I'm learning this project. I'm not the
author, I just cloned the v0.1.0 release and started poking at it. I'll
keep adding to these as I figure more out.

Read in this order if you're new like me:

1. [`01-running.md`](01-running.md) — how I installed it and what I ran.
2. [`02-architecture.md`](02-architecture.md) — what I understand about
   how the code is organized + the public API.
3. [`examples/`](examples/) — small Python scripts I wrote to play with
   the DSL, from simplest to slightly less simple.

If I had to explain the project to myself in one sentence:

> You write Datalog-like rules in Python, the library compiles them
> down to C++/CUDA source code, then clang + ninja build that into a
> `.so` file that you call from Python with ctypes.

So Python is mostly the *frontend / compiler driver*. The real engine
is the generated C++/CUDA code.

Things I'm still fuzzy on (will update as I learn):

- The exact difference between HIR and MIR passes.
- What semi-naive evaluation actually looks like in the generated C++.
- How the GPU index types (Device2LevelIndex etc.) are picked.
- What "work stealing" means in this codebase and why it blocks 2/127
  fixtures.
