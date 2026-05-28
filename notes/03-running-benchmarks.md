# Running real benchmarks — what I learned

After the small `01_hello` / `02_transitive_closure/...` toy examples,
I downloaded the official Hugging Face dataset
([ysun67/srdatalog-benchmark](https://huggingface.co/datasets/ysun67/srdatalog-benchmark))
and ran real benchmarks on real CSVs. This file collects what I
found and what I still want to try.

If you have not downloaded the dataset yet, see `01-running.md` for
the download/unzip commands. After unzipping, everything lives under:

```text
/data/srdatalog_benchmark/data/
```

The folders are: `andersen/`, `ddisasm/`, `doop/`, `galen/`, `lsqb/`,
`polonius/`, `sg/`.

---

## Benchmarks I actually ran

### 1. TC (transitive closure) on `sg/usroad_small`

Command:

```bash
uv run python examples/run_benchmark.py tc \
  --data data/srdatalog_benchmark/data/sg/usroad_small \
  --max-iter 3
```

Result:

- Compile: ~33s cold (one-time).
- The TC program’s `Arc.csv` convention happened to match
  `sg/usroad_small/Arc.csv` exactly, so it loaded fine.
- The runner itself printed:

```text
>>>>>>>>>>>>>>>>> Path : 48413     (with --max-iter 3)
>>>>>>>>>>>>>>>>> Path : 1178627   (full fixpoint)
```

- But the script’s final summary block printed `Path: 0`. See the
  caveat below — this is consistent across benchmarks.

### 2. Galen on `galen/galen`

Command (capped):

```bash
uv run python examples/run_benchmark.py galen \
  --data /home/jinyang/Code/srdatalog/data/srdatalog_benchmark/data/galen/galen \
  --max-iter 3
```

Then unlimited:

```bash
uv run python examples/run_benchmark.py galen \
  --data /home/jinyang/Code/srdatalog/data/srdatalog_benchmark/data/galen/galen
```

Result:

- 8 relations, 8 rules, emit produces `main + 2 batches`.
- Compile cold: ~40s. Re-runs after that are instant (ccache).
- With `--max-iter 3`:

```text
OutP : 2,728,380
OutQ : 2,552,375
```

- With unlimited fixpoint:

```text
OutP : 7,560,179
OutQ : 16,595,494
```

- So 3 iterations was only partial — the real fixpoint produces a
  lot more.
- Unlimited run **exited 139** (segfault), but only *after* the
  results were printed. Looks like a crash during shutdown.

### 3. Doop on `doop/eclipse_interned`

Command:

```bash
uv run python examples/run_benchmark.py doop \
  --data /home/jinyang/Code/srdatalog/data/srdatalog_benchmark/data/doop/eclipse_interned \
  --meta /home/jinyang/Code/srdatalog/data/srdatalog_benchmark/data/doop/eclipse_interned/meta.generated.json \
  --max-iter 1
```

Result:

- 74 relations, 78 rules, **16 dataset_consts**, 12 batch files.
- Compile cold: ~80s. Bigger codegen = bigger compile.
- The runner printed lots of relation sizes, for example:

```text
SubtypeOf            : 18,314
MethodLookup         : 93,934
CastTo               : 18,529,905
HeapAllocSuperType   : 48,045,930
```

- The final summary block reported all zeros, same caveat.

---

## Findings (the “gotchas”)

### A. The final `=== Result sizes ===` block always shows 0

Every benchmark I ran showed real, non-zero relation sizes from the
runner itself:

```text
>>>>>>>>>>>>>>>>> OutP : 7560179
```

But the script’s final summary block:

```text
=== Result sizes ===
OutP                                        0
```

…always reported 0. So:

> Trust the `>>>>>>>>>>>>>>>>> RelName : N` lines, not the final
> `srdatalog_size(...)` block.

That summary uses `lib.srdatalog_size(rel.name.encode())` (see
`examples/run_benchmark.py` around the `=== Result sizes ===`
print). Something is off in either the symbol/handle being read or
the host-side mirror of the relation. The actual fixpoint clearly
runs — the runner prints prove it.

### B. Some `meta.json` files are incomplete

`examples/doop.py` needs **16** dataset_const keys, including:

- `java_lang_Class_type`
- `java_lang_Object_array`
- `java_lang_String_type`

The shipped `doop/eclipse_interned/meta.json` is missing those.
You get a `KeyError` immediately when the benchmark builds.

Fix: derive the missing keys from `str2num.json` and write a new
meta file. The keys I used:

| meta key | string to look up in `str2num.json` |
|---|---|
| `java_lang_Class_type` | `<class java.lang.Class>` |
| `java_lang_Object_array` | `<class java.lang.Object[]>` |
| `java_lang_String_type` | `<class java.lang.String>` |

I saved the result as `meta.generated.json` next to the original
`meta.json` and passed it via `--meta`.

(If you re-clone the dataset, do the same fix-up, or run
`examples/doop_run.py` which uses defaults from an older path that
won’t exist on your box.)

### C. Recursive benchmarks: `--max-iter N` is *partial*

`--max-iter 3` does NOT mean "small dataset"; it means "stop the
fixpoint after 3 iterations and tell me what you've got". For
benchmarks like Galen, that is far from the true fixpoint —
between 3 iterations and unlimited the result jumped roughly:

```text
OutP:  2.7M  → 7.5M
OutQ:  2.5M  → 16.6M
```

Useful for sanity checks; not useful for measuring real result
sizes.

### D. Compile is the slow part. Run is fast.

Times I saw:

| Benchmark | Compile cold | Compile warm (ccache) | Run     |
|---|---|---|---|
| tc        | ~33s | ~0s | <1s |
| galen     | ~40s | ~0s | 0.3s |
| doop      | ~80s | ~0s | 0.2s (max_iter=1) |

So as long as you don’t blow away `./build/`, iterating on the
same program is basically instant on the second compile.

### E. Galen full run exits 139 (segfault on shutdown)

The unlimited Galen run printed correct result sizes, then exited
with code **139**. Nothing important is lost (the run finished and
printed results), but a clean exit would be nicer. Probably a
shutdown / dtor issue in the generated runner.

### F. The benchmark data uses different folder names than the Python expects

Each translated Datalog program (`examples/<benchmark>.py`) hardcodes
specific input filenames via `input_file="..."`. The dataset folders
sometimes use different conventions:

- `sg/usroad_small/Arc.csv` — matches `tc.py`’s `ArcInput =
  Relation(..., input_file="Arc.csv")` exactly.
- `galen/galen/{P,Q,R,S,U,C}.csv` — matches `galen.py` exactly.
- Doop datasets are interned vs raw (`batik` vs `batik_interned`).
  The Python benchmarks expect the **interned** form.

The lesson: before running a benchmark, open `examples/<benchmark>.py`
and read the `input_file=...` lines. Then point `--data` at a folder
whose CSV names match.

### G. Disk planning

Extracted dataset takes ~22G. After extracting plus building Doop
cache, free space on this box dropped from 110G → 89G. Worth
keeping an eye on if you build many benchmarks.

---

## TODO list for myself

In rough order of usefulness for understanding the project.

### Correctness / open questions
- [ ] Figure out why `srdatalog_size(rel_name)` returns 0 even
  when the runner clearly produced non-zero rows. Likely a host/device
  mirror or canonical-index lookup mismatch.
- [ ] Reproduce the Galen exit-139 segfault in a smaller setting
  to see if it’s the same issue (probably in `srdatalog_shutdown`).
- [ ] Write a tiny `meta.json` generator that reads `str2num.json`
  and produces a complete meta file. Right now I did it manually
  for `eclipse_interned`.

### Bigger benchmarks I haven’t tried yet
- [ ] Doop on `batik_interned` (~1 GB CSVs) — the canonical Doop run.
- [ ] Doop on `biojava` / `xalan` / `zxing` — need to check whether
  they ship a `meta.json` or need generating.
- [ ] DDisasm on `data/ddisasm/lean4` (small) — needs
  `ddisasm_consts.json` as `--meta`, check whether it’s complete.
- [ ] DDisasm on `data/ddisasm/z3` (big).
- [ ] Andersen on `andersen/andersen-medium` then `andersen-large`.
- [ ] Polonius on `data/polonius/*` — there are multiple subfolders;
  unclear which one matches `polonius_test.py`.
- [ ] One of the LSQB queries (`lsqb_q3_triangle`, etc.) on
  `data/lsqb/sf10/`.

### Understanding the system
- [ ] Open the `jit_batch_*.cpp` from the Galen run and try to map
  each section back to a MIR step (the generated code has
  comments — see Yihao’s note in `02-architecture.md`).
- [ ] Pick one rule like Galen’s `Join3a` and inspect the index
  type it ends up using (e.g. via `compile_to_hir`/HIR strata) so
  I understand the planner’s output.
- [ ] Run `compile_to_hir` on Doop and Galen to see how many strata
  / variants the analyzer produces.
- [ ] Try changing `.with_plan(var_order=...)` on a Galen rule and
  see how compile/run time changes — Yihao said real benchmarks
  rely on manual ordering.

### Convenience
- [ ] Add a small shell wrapper that takes a benchmark name + dataset
  subfolder and runs it with the right `--meta` / cache settings.
- [ ] Add `output_file="..."` to a couple of result relations so
  the runtime writes results to disk (then I can validate output
  independent of `srdatalog_size`).

---

## summary

The pipeline really does work end to end on real datasets. The
program shapes are what i expect (recursive fixpoint, growing
result counts iteration over iteration). The places it currently
hurts are: the final `srdatalog_size` readback is unreliable, some
dataset `meta.json`s are incomplete, and shutdown can crash on big
runs.
