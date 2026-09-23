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

## Not measured

- Line or branch coverage of the Verilog (no coverage-capable simulator in this setup)
- Other values of `DEPTH` and `DATA_WIDTH`
