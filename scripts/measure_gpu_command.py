'''Run a command while sampling NVIDIA GPU memory.

Example:

    python scripts/measure_gpu_command.py -- \
      python examples/run_benchmark.py triangle
'''

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from contextlib import suppress
from dataclasses import dataclass


@dataclass
class Sample:
  timestamp: float
  used_mib: tuple[int, ...]
  rss_kib: int = 0


def _query_used_mib() -> tuple[int, ...]:
  out = subprocess.check_output(
    [
      "nvidia-smi",
      "--query-gpu=memory.used",
      "--format=csv,noheader,nounits",
    ],
    text=True,
  )
  return tuple(int(line.strip()) for line in out.splitlines() if line.strip())


def _process_tree_rss_kib(root_pid: int) -> int:
  children_by_parent: dict[int, list[int]] = {}
  for proc_dir in os.scandir("/proc"):
    if not proc_dir.name.isdigit():
      continue
    try:
      stat = open(f"/proc/{proc_dir.name}/stat", encoding="utf-8").read()
      fields_after_name = stat.rsplit(")", 1)[1].split()
      ppid = int(fields_after_name[1])
      children_by_parent.setdefault(ppid, []).append(int(proc_dir.name))
    except (FileNotFoundError, IndexError, OSError, ValueError):
      continue

  total = 0
  pending = [root_pid]
  seen: set[int] = set()
  while pending:
    pid = pending.pop()
    if pid in seen:
      continue
    seen.add(pid)
    pending.extend(children_by_parent.get(pid, ()))
    try:
      with open(f"/proc/{pid}/status", encoding="utf-8") as status:
        for line in status:
          if line.startswith("VmRSS:"):
            total += int(line.split()[1])
            break
    except (FileNotFoundError, OSError, ValueError):
      continue
  return total


def _sample_loop(
  samples: list[Sample],
  done: threading.Event,
  interval_s: float,
  root_pid: int,
) -> None:
  while not done.is_set():
    rss_kib = _process_tree_rss_kib(root_pid)
    try:
      samples.append(Sample(timestamp=time.time(), used_mib=_query_used_mib(), rss_kib=rss_kib))
    except Exception as exc:
      print(f"[gpu] sample failed: {exc}", file=sys.stderr)
      samples.append(Sample(timestamp=time.time(), used_mib=(), rss_kib=rss_kib))
    done.wait(interval_s)


def _signal_process_group(proc: subprocess.Popen[object], sig: signal.Signals) -> None:
  with suppress(ProcessLookupError):
    os.killpg(proc.pid, sig)


def _wait_with_timeout(proc: subprocess.Popen[object], timeout_s: float | None) -> tuple[int, bool]:
  if timeout_s is None:
    return proc.wait(), False

  deadline = time.time() + timeout_s
  while True:
    try:
      return proc.wait(timeout=0.25), False
    except subprocess.TimeoutExpired:
      if time.time() < deadline:
        continue

      _signal_process_group(proc, signal.SIGINT)
      try:
        return proc.wait(timeout=10.0), True
      except subprocess.TimeoutExpired:
        _signal_process_group(proc, signal.SIGKILL)
        return proc.wait(), True


def main() -> int:
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument(
    "--interval",
    type=float,
    default=0.25,
    help="Sampling interval in seconds.",
  )
  parser.add_argument(
    "--timeout",
    type=float,
    default=None,
    help="Stop the command after this many seconds and still print measurements.",
  )
  parser.add_argument("cmd", nargs=argparse.REMAINDER, help="Command to run after --.")
  args = parser.parse_args()

  cmd = args.cmd
  if cmd and cmd[0] == "--":
    cmd = cmd[1:]
  if not cmd:
    parser.error("missing command after --")

  samples: list[Sample] = []
  done = threading.Event()

  start_used = _query_used_mib()
  start_time = time.time()
  proc = subprocess.Popen(cmd, start_new_session=True)
  sampler = threading.Thread(
    target=_sample_loop,
    args=(samples, done, args.interval, proc.pid),
    daemon=True,
  )
  sampler.start()
  timed_out = False
  try:
    returncode, timed_out = _wait_with_timeout(proc, args.timeout)
  except KeyboardInterrupt:
    _signal_process_group(proc, signal.SIGINT)
    try:
      returncode = proc.wait(timeout=10.0)
    except subprocess.TimeoutExpired:
      _signal_process_group(proc, signal.SIGKILL)
      returncode = proc.wait()
    timed_out = False
  finally:
    done.set()
    sampler.join(timeout=max(1.0, args.interval * 2.0))
  end_time = time.time()
  end_used = _query_used_mib()

  peak_used = max(
    (max(sample.used_mib, default=0) for sample in samples),
    default=max(start_used, default=0),
  )
  start_max = max(start_used, default=0)
  end_max = max(end_used, default=0)
  peak_delta = max(0, peak_used - start_max)
  peak_rss_kib = max((sample.rss_kib for sample in samples), default=0)
  peak_rss_mib = peak_rss_kib / 1024.0

  print(
    "[gpu] "
    f"samples={len(samples)} "
    f"elapsed={end_time - start_time:.2f}s "
    f"start_used_mib={start_max} "
    f"peak_used_mib={peak_used} "
    f"peak_delta_mib={peak_delta} "
    f"end_used_mib={end_max} "
    f"peak_rss_mib={peak_rss_mib:.1f} "
    f"timed_out={str(timed_out).lower()} "
    f"returncode={returncode}",
    flush=True,
  )
  return returncode


if __name__ == "__main__":
  raise SystemExit(main())
