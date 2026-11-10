#!/usr/bin/env python3
"""
triage.py -- run the cocotb suite across many seeds and sort every failure.

A red test run on its own says almost nothing. The questions that decide
what to do next are:

  1. Does it fail again with the same seed?   no  -> FLAKY: the result depends
                                                     on something other than the
                                                     seed and the design (timing,
                                                     leftover state, environment).
  2. Does it fail on every seed?              yes -> EVERY SEED: a systematic
                                                     problem, usually the design
                                                     (or a test that can never pass).
                                              no  -> SOME SEEDS: only certain
                                                     random traffic reaches it; a
                                                     real corner-case bug or a
                                                     testbench fault. Replay one of
                                                     the listed seeds to find out.

The tool answers those questions automatically:
  - runs the suite once per seed (each run writes its own JUnit results file)
  - reruns every failing (test, seed) pair on its own, with the same seed
  - groups failures by message, so ten seeds hitting one bug show up as one row
  - writes a Markdown report and a JSON file, and prints the exact replay command

Exit code: 0 if nothing failed, 1 if any test failed reproducibly,
2 if the only failures were flaky.

    python tools/triage.py --seeds 20                 # sync suite, seeds 1..20
    python tools/triage.py --target async --seeds 10
    python tools/triage.py --module test_triage_demo  # the tool's own self-test
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FLAKY, EVERY_SEED, SOME_SEEDS = "flaky", "fails on every seed", "fails on some seeds"


@dataclass
class Failure:
    test: str
    seed: int
    message: str
    reruns: list[bool] = field(default_factory=list)  # True = failed again


def signature(message: str) -> str:
    """Failure message with numbers removed, so the same bug on different seeds groups together."""
    lines = [l.strip() for l in message.splitlines() if re.search(r"[A-Za-z0-9]", l)]
    first = lines[0] if lines else "(no message)"
    return re.sub(r"0x[0-9a-fA-F]+|\d+", "N", first)[:160]


def run_suite(args, seed: int, out_xml: Path, test_filter: str | None = None) -> dict[str, str | None]:
    """Run make once; return {test name: failure message or None if it passed}."""
    out_xml.parent.mkdir(parents=True, exist_ok=True)
    out_xml.unlink(missing_ok=True)
    cmd = ["make", "-s", f"SIM_TARGET={args.target}", f"RANDOM_SEED={seed}",
           f"COCOTB_RESULTS_FILE={out_xml}",
           f"COVERAGE_XML={args.out / 'scratch_coverage.xml'}",
           f"COVERAGE_ASYNC_XML={args.out / 'scratch_coverage_async.xml'}"]
    if args.module:
        cmd.append(f"MODULE={args.module}")
    if test_filter:
        cmd.append(f"COCOTB_TEST_FILTER={test_filter}$$")  # regex searched in module.test; $$ is make for $
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if not out_xml.exists():
        sys.exit(f"make produced no results file (exit {proc.returncode}):\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}")
    results = {}
    for case in ET.parse(out_xml).getroot().iter("testcase"):
        fail = case.find("failure")
        if fail is None:
            fail = case.find("error")
        if case.find("skipped") is not None:
            continue
        msg = None if fail is None else (fail.get("message") or fail.text or "failed")
        results[case.get("name")] = msg
    return results


def classify(failures: list[Failure], seeds: list[int]) -> dict:
    by_test: dict[str, list[Failure]] = defaultdict(list)
    for f in failures:
        by_test[f.test].append(f)
    rows = []
    for test, fs in sorted(by_test.items()):
        flaky = [f for f in fs if not all(f.reruns)]
        solid = [f for f in fs if all(f.reruns)]
        if flaky:
            rows.append({"test": test, "verdict": FLAKY, "seeds": sorted(f.seed for f in flaky),
                         "reruns": {f.seed: f"{sum(f.reruns)}/{len(f.reruns)} failed again" for f in flaky},
                         "signatures": sorted({signature(f.message) for f in flaky})})
        if solid:
            verdict = EVERY_SEED if len(solid) == len(seeds) else SOME_SEEDS
            rows.append({"test": test, "verdict": verdict, "seeds": sorted(f.seed for f in solid),
                         "signatures": sorted({signature(f.message) for f in solid})})
    return {"rows": rows}


def report_markdown(args, seeds, summary, rows, elapsed) -> str:
    lines = [f"# Triage report: {args.module or ('test_' + args.target + '_fifo')}", "",
             f"{len(seeds)} seeds ({seeds[0]} to {seeds[-1]}), {args.reruns} reruns per failure, {elapsed:.0f} s.", "",
             f"- Test runs: {summary['runs']}, failed: {summary['failed_runs']}",
             f"- Reproducible failures: {summary['reproducible']}, flaky: {summary['flaky']}", ""]
    if not rows:
        lines.append("All tests passed on every seed.")
        return "\n".join(lines) + "\n"
    lines += ["| Test | Verdict | Seeds | Failure signature |", "|---|---|---|---|"]
    for r in rows:
        seeds_txt = ", ".join(map(str, r["seeds"][:12])) + (" ..." if len(r["seeds"]) > 12 else "")
        lines.append(f"| `{r['test']}` | **{r['verdict']}** | {len(r['seeds'])}: {seeds_txt} | "
                     f"{'<br>'.join(s.replace('|', '/') for s in r['signatures'])} |")
    lines += ["", "Replay one failure on its own:", ""]
    for r in rows:
        mod = f" MODULE={args.module}" if args.module else ""
        lines.append(f"    make SIM_TARGET={args.target}{mod} RANDOM_SEED={r['seeds'][0]} "
                     f"COCOTB_TEST_FILTER='{r['test']}$$'   # {r['verdict']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", choices=["sync", "async"], default="sync")
    p.add_argument("--module", help="cocotb test module to run instead of the target's own suite")
    p.add_argument("--seeds", type=int, default=20, help="run seeds 1..N")
    p.add_argument("--first-seed", type=int, default=1)
    p.add_argument("--reruns", type=int, default=3, help="reruns of each failing test with the same seed")
    p.add_argument("--out", type=Path, default=ROOT / "results" / "triage")
    args = p.parse_args()
    args.out = args.out.resolve()
    seeds = list(range(args.first_seed, args.first_seed + args.seeds))

    start = time.time()
    failures: list[Failure] = []
    runs = 0
    for seed in seeds:
        results = run_suite(args, seed, args.out / "runs" / f"seed_{seed}.xml")
        runs += len(results)
        failures += [Failure(t, seed, m) for t, m in results.items() if m is not None]
        print(f"seed {seed:>4}: {sum(m is None for m in results.values())}/{len(results)} passed", flush=True)

    for f in failures:
        for k in range(args.reruns):
            again = run_suite(args, f.seed, args.out / "reruns" / f"{f.test}_seed{f.seed}_{k}.xml", f.test)
            if f.test not in again:
                sys.exit(f"rerun of {f.test} (seed {f.seed}) ran no such test; check COCOTB_TEST_FILTER")
            f.reruns.append(again[f.test] is not None)

    rows = classify(failures, seeds)["rows"]
    summary = {"runs": runs, "failed_runs": len(failures),
               "reproducible": sum(all(f.reruns) for f in failures),
               "flaky": sum(not all(f.reruns) for f in failures)}
    elapsed = time.time() - start
    md = report_markdown(args, seeds, summary, rows, elapsed)
    (args.out / "triage_report.md").write_text(md)
    (args.out / "triage_report.json").write_text(json.dumps(
        {"target": args.target, "module": args.module, "seeds": seeds, "reruns": args.reruns,
         "summary": summary, "rows": rows,
         "failures": [f.__dict__ for f in failures]}, indent=2))
    print("\n" + md)
    sys.exit(0 if not failures else (1 if summary["reproducible"] else 2))


if __name__ == "__main__":
    main()
