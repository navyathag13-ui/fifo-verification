# What I re-ran (2026-09-23)

Machine: Apple M4 MacBook, macOS 26.5.1. I cloned this repo fresh into a temporary folder (commit `b637323`) and ran everything from there.

Tools: Icarus Verilog 13.0, cocotb 2.1.0, Yosys 0.69, Z3 (SymbiYosys `sby`), Python 3.11.

| Command | Result |
|---|---|
| `make` (sync FIFO) | `TESTS=10 PASS=10 FAIL=0` |
| `make async` | `TESTS=8 PASS=8 FAIL=0` |
| `sby -f formal/sync_fifo.sby` | `DONE (PASS, rc=0)` |
| `sby -f formal/async_fifo.sby` | `DONE (PASS, rc=0)` |

Functional coverage, read from the run's own `results/coverage.xml` and `results/coverage_async.xml`: the sync suite hit 7 of 7 corner-case bins and the async suite hit 7 of 7. (Each XML file also lists the other design's bins at 0%, because both covergroups are defined in the same module; that is not a gap.)

The formal runs use `mode bmc` at `depth 16`, so they check every behaviour up to 16 cycles, which covers a full fill and drain of the 16-deep FIFO. They are not unbounded proofs.

Two hiccups while re-running, both about the environment and not the design: `make` fails if the project path contains a space, and running `make async` right after `make` fails until `results/sim_build` is removed, because the previous simulation build is reused.


## Later the same day: flaky random test found and fixed

Re-running the sync suite with random seeds (the default) showed it was flaky. Before the fix: 3 failures in 8 runs. The failure was never a design bug: `test_random_traffic` asserts that the random traffic reached every corner case, and some seeds missed one (first "simultaneous push and pop while full", then, after I fixed that, "multiple consecutive resets"). After changing the traffic to run in phases and to reset in bursts:

| Run | Result |
|---|---|
| Sync, 40 random seeds | 40 of 40 pass |
| Async, 25 random seeds | 25 of 25 pass |
| Sweep, `DEPTH` 4/8/16/32 x `DATA_WIDTH` 8/16, sync and async | 16 of 16 configurations pass (10/10 and 8/8 each) |
| RTL mutant: `full` ignores the wrap bit | 9 of 10 sync tests fail (suite still catches it) |
| RTL mutant: `empty` stuck at 0 | 7 of 10 sync tests fail |
| Original RTL restored | 10 of 10 pass |

The earlier line in this file saying the suite passed 10/10 was a single run that happened to use a lucky seed.

## Still not measured

- Line or branch coverage of the Verilog
- Formal checks at anything other than the default size (depth 16, width 8)
