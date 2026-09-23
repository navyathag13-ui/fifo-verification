# Parameterized FIFO Verification Suite (Sync + Async) — cocotb

Two parameterized FIFOs in Verilog, one single-clock, one dual-clock (async), both verified with Python-based [cocotb](https://www.cocotb.org/) testbenches. Same philosophy I apply on the software side: fuzz until it stops finding anything, track coverage so you actually know the fuzzing reached the interesting states, and write tests that assume the design is broken rather than tests that just confirm it isn't. The FIFOs themselves aren't the hard part — pointers, a comparator, a memory array. The verification is the actual project here. Directed tests for the specific ways FIFOs break in practice, randomized tests that check the DUT against a plain Python reference model instead of a fixed list of expected inputs, and for the async design, the thing that actually makes async FIFOs a respected skill: clock-domain-crossing correctness, not just the FIFO logic sitting on top of it.

## Highlights

- Two parameterized FIFOs in Verilog: a single-clock one, and a **dual-clock one with Gray-coded pointers and synchronizers**
- **18 cocotb tests** (10 sync, 8 async) passing, including a 5,000-cycle randomized test checked against a Python reference model
- Formal checking with **SymbiYosys and Z3** on both designs
- Tests that I proved can fail, by planting bugs in the RTL and watching the suite catch them
- Functional coverage of every corner case I listed (7 of 7 in each suite), on every random seed I tried
- Passes across 40 random seeds (sync) and 25 (async), and at 16 different depth and width combinations
- Found and fixed a flaw in my own random test (it failed about 3 runs in 8) by shaping the traffic so every corner case is reached


## Why I built this

A FIFO looks like the simplest thing in digital design, and it is also where a lot of real hardware bugs hide: a full flag that goes high one cycle late, a push that sneaks in while the buffer is full, a reset that clears one pointer and forgets the other. The dual-clock version is harder still, because data crosses between two clocks that have no fixed relationship.

I wanted to practise the part of hardware work I find most interesting, which is not writing the design but convincing yourself (and a reviewer) that it works. So this repo has two small FIFOs in Verilog, one on a single clock and one on two, and a lot of effort spent on checking them: directed tests, a randomized test against a reference model, coverage counting, bugs I planted on purpose to make sure the tests notice, and formal checks.

## Tech stack

| Piece | What I used |
|---|---|
| Design | Verilog (compiled as strict IEEE 1364-2005 so no SystemVerilog sneaks in), both FIFOs parameterized by `DATA_WIDTH` (default 8) and `DEPTH` (default 16, a power of two); Gray-coded pointers and two-flop synchronizers in the async one |
| Simulation | Icarus Verilog 13.0 |
| Testbenches | cocotb 2.1 (Python), with a plain Python `deque` as the reference model |
| Coverage | cocotb-coverage 2.x (functional coverage of corner cases) |
| Formal | SymbiYosys with Yosys and the Z3 solver, SystemVerilog assertion wrappers kept separate from the design |
| Automation | Make |

## What I found

I re-ran everything from a fresh `git clone` on 2026-09-23 (commit `b637323`, Apple M4 Mac). The details are in [`VERIFICATION.md`](VERIFICATION.md).

| Check | Result |
|---|---|
| Sync FIFO, cocotb | 10 of 10 tests pass, including a 5,000-cycle randomized run compared against the Python model. Across 40 different random seeds: 40 of 40 pass. |
| Async (dual-clock) FIFO, cocotb | 8 of 8 tests pass. Across 25 different random seeds: 25 of 25 pass. |
| Other sizes | Both suites also pass at `DEPTH` 4, 8, 16 and 32 with `DATA_WIDTH` 8 and 16 (16 configurations, `make sweep`) |
| Formal checks | Both FIFOs pass bounded model checks to depth 16, which explores a full fill and drain exhaustively. I also tried k-induction on the sync design; the "Formal verification" section explains what that showed and the invariant work it points to. |
| Do the tests actually catch bugs? | Yes. I broke the RTL on purpose (for example the full flag's wrap bit) and each suite failed as it should. The sections named "Proving the ... tests can actually fail" show the failures. |
| Functional coverage | Sync hits 7 of 7 corner-case bins and async hits 7 of 7 (counts are in the tables below) |
| Code coverage of the Verilog | Functional coverage is the metric used here. Adding line and branch coverage with a coverage-capable simulator such as Verilator is on the roadmap. |

**Scope:** simulation across 8 configurations per FIFO (depth 4 to 32, width 8 and 16) plus bounded formal checks on the default size (depth 16, width 8). The async design is checked for the CDC-safe pattern (Gray coding, two synchronizer stages, the full-flag inversion rule); a static CDC sign-off tool is the next step toward silicon.

## How it came together

1. Wrote the sync FIFO and one directed test per real bug class (full and empty boundaries, push while full, pop while empty, simultaneous push and pop, resets in the middle of traffic).
2. Added the randomized test with a Python reference model, then counted which corner cases it actually reached, so I knew it wasn't just passing by never visiting the hard cases.
3. Planted bugs to check that the suite fails when it should.
4. Built the async FIFO (Gray code pointers, synchronizers) and a testbench with two clocks at different rates.
5. Added formal checks for the things simulation cannot exhaust.

6. Ran the suite over many random seeds. That exposed a flaw in my own test: with a random seed, the sync suite failed about 3 runs in 8. The design was fine every time (it always matched the reference model); the failure was the test's own check that the random traffic had reached every corner case. A flat 50/50 push/pop mix rarely sat at full, and independent 2% resets almost never came back to back. I changed the traffic to run in phases (balanced, fill-heavy, drain-heavy, both-heavy) and to reset in bursts. It now passes 40 of 40 random seeds, and I re-checked that the suite still fails when I break the RTL on purpose (9 of 10 tests fail with the wrap bit removed, 7 of 10 with `empty` stuck low).
7. Added `DEPTH` and `DATA_WIDTH` overrides and a sweep across sizes. Each configuration builds in its own folder, which also removed an earlier annoyance where switching between `make` and `make async` reused a stale build.

One practical note if you run it yourself: `make` does not like folder paths that contain spaces.

---

## Sync FIFO

### Why these test cases

Every directed test here is aimed at one specific way FIFOs actually break. Not a generic "does it work" pass.

| Test | Real bug class it targets |
|---|---|
| `test_reset_behavior` | Reset that looks correct from a freshly-elaborated (all-zero) sim but doesn't actually *clear* anything. Dirties the FIFO first so a no-op reset can't hide behind a lucky initial state. |
| `test_single_write_read` | Basic data-path integrity, accounting for the one-cycle registered read latency. Everything else assumes this holds. |
| `test_fill_to_full` | Off-by-one on the full boundary. Assert `full` one cycle early and you waste a slot; one cycle late and an overflow silently eats the oldest unread entry. |
| `test_push_when_full` | A push that gets accepted anyway while `full` is high — the classic overflow. Checked by confirming the oldest entry is still intact afterward, not just that `full` stayed asserted. |
| `test_pop_when_empty` | A pop accepted while empty either hands back garbage as if it were real data, or corrupts the read pointer so every later read is off by one. Pop while empty, then confirm a real subsequent read still lands right. |
| `test_simultaneous_push_pop` | Push and pop on the same clock edge — exactly where a counter-based fill-tracking scheme tends to get the increment/decrement backwards. A pointer-based design should just handle this, but only if both pointers are wired independently. |
| `test_reset_mid_transaction` | A *partial* reset — say, one that clears `wr_ptr` but leaves `rd_ptr` stale. Testing reset only from a clean idle state would never catch this. |
| `test_back_to_back_single_cycle` | Push and pop every single cycle, wrapping the pointer address space several times. This is what real pipeline traffic looks like, and it's where a wraparound or address bug shows up as corrupted data long before a handful of directed pushes would ever find it. |
| `test_boundary_depth_minus_one_and_plus_one` | The exact off-by-one line: `DEPTH-1` must not read full, exactly `DEPTH` must, and a rejected `DEPTH+1`th push has to leave things exactly as a clean fill would — not corrupted, not silently accepted. |

### Randomized testing

The directed tests above cover what I thought to check. `test_random_traffic` exists because the bugs that actually make it to production are usually the ones nobody thought to write a directed test for. Same reasoning as coverage-guided fuzzing on the software side — AFL++, mutation fuzzing with Radamsa. Don't just test the inputs you imagined; throw a long adversarial sequence at it and let a trusted oracle catch what slips through.

The oracle is `ref_model.py`, a plain Python `deque`. Not another piece of RTL — no risk of the reference sharing a bug with the thing it's checking. It matches two subtleties of the RTL exactly rather than approximately:

Registered read latency. `rd_data` in the RTL is `rd_data <= mem[rd_addr]`, a register, not a wire, so a pop issued on cycle N only shows up on `rd_data` starting cycle N+1. `RefFifo.rd_data` does the same — only updates inside `step()` after a real pop, holds otherwise.

Both operations gated against the same pre-edge state. Write and read live in two separate `always @(posedge clk)` blocks in the RTL, each gated on full/empty as it stood before that edge. `step()` grabs `full`/`empty` once at the top and uses those same captured values for both decisions, so a same-cycle push+pop gets evaluated exactly like the hardware does — two simultaneous decisions against one shared prior state, never push-then-pop or the other way around.

Every cycle for 5,000 cycles (`RANDOM_CYCLES` is configurable), the test picks push, pop, both, neither, or occasionally reset, drives the DUT, steps the reference model with the same inputs, compares `full`, `empty`, and `rd_data` where relevant. Any mismatch fails immediately, with the exact cycle and the last 20 operations printed out. I wanted this to read like a minimized fuzzing crash report, not a bare `assert False`:

```
==============================================================================
RANDOM TRAFFIC TEST FAILURE -- minimized reproduction context
==============================================================================
Seed:              42
Failed at cycle:   1 / 5000
Mismatches:        full: DUT=True REF=False; empty: DUT=True REF=False

Last operations leading to failure (oldest first):
  cycle 1: wr_en=1 wr_data=0x72 rd_en=1 -> DUT(full=1,empty=1,rd_data=0x00) REF(full=0,empty=0)
==============================================================================
```

That's a real failure, by the way — from deliberately breaking `full`'s wrap-bit check to make sure the suite actually catches things. More on that below.

### Coverage

Using [cocotb-coverage](https://github.com/mciepluc/cocotb-coverage) for this, not a hand-rolled dict. It's still actively maintained (v2.0 in October 2025, adjusted for cocotb ≥2.0) and it's the tool the ecosystem actually uses — same CRV/MDV coverage model SystemVerilog verification environments have used forever. Each bin here is single-bin hit/miss: "covered" means the random test reached that state at least once, the RTL equivalent of a gcov line hit, not a value-domain thing.

| Corner case | Hit? |
|---|---|
| FIFO reached full | ✅ |
| FIFO reached empty | ✅ |
| Simultaneous push+pop while full | ✅ |
| Simultaneous push+pop while empty | ✅ |
| Reset while non-empty | ✅ |
| Back-to-back push-then-pop | ✅ |
| Multiple consecutive resets | ✅ |

7/7 on every seed I tried (40 random seeds plus the fixed seed 42). The report records hit or miss for each corner, not how many times it was hit; an earlier version of this table listed hit counts that came from the old fixed 50/50 traffic, and I removed them because they no longer describe the current stimulus. The rare corners are full and simultaneous push+pop while full, which need a long run of net pushes, and back-to-back resets. That is why the traffic runs in phases and resets come in bursts.

### Proving the sync tests can actually fail

A green suite and a nice coverage number don't mean much if the tests can't actually catch anything. So I broke `full`'s wrap-bit check on purpose:

```verilog
// BUG: missing wrap-bit check, aliases with empty
assign full = (wr_addr == rd_addr);
```

Reran the suite. 8 of 9 directed tests failed right away, each pointing at the actual symptom (`full asserted early, before push 0/16`, `read pointer corrupted by earlier no-op pop`, that kind of thing), and `test_random_traffic` caught it on cycle 1 with the exact mismatch shown above. Reverted the bug, confirmed all 10 pass again. Inject a real bug, watch the suite scream, put it back, confirm it goes quiet — same thing you'd do checking a fuzz harness against a known-bad build before trusting a clean result against the real one.

## Async (dual-clock) FIFO

`rtl/async_fifo.v` follows the standard Cummings design (Clifford E. Cummings, "Simulation and Synthesis Techniques for Asynchronous FIFO Design," SNUG 2002) — the reference everyone points to for this. Binary pointers for addressing memory, Gray-coded twins for anything crossing domains, a 2-flop synchronizer on each crossing, full/empty computed from Gray-code comparisons and registered so neither flag ever glitches.

### Why Gray code, and why this is the actual hard part

A binary counter can flip several bits at once — `0111 → 1000` flips four. Synchronize a multi-bit binary value across clock domains and there's no guarantee every bit lands on the far side in the same cycle. A synchronizer catching it mid-transition can read a torn value that was never valid at any point in time, not just a stale one. Gray code kills this at the root: exactly one bit changes per increment, so mid-transition you read either the old value or the new one, never something that never existed. This, not the FIFO logic (which is barely different from the sync version), is why async FIFO design and verification gets treated as the harder, more senior thing. Getting this wrong is a real CDC-class bug, not a toy one.

### Why the verification looks completely different here

The sync suite compares against a reference model every single cycle. That comparison doesn't mean anything here — there's no shared "cycle" between two clocks that have nothing to do with each other. What does survive across any clock relationship is data integrity: whatever comes out has to be the next value, in order, of whatever went in. `ref_model.OrderedIntegrityChecker` checks exactly that. A plain queue of expected values, pushed on one side, checked on the other. Nothing about timing, nothing about which cycle anything happened on.

The testbench itself is two independent coroutines — a writer on `wr_clk`, a reader on `rd_clk` — each driving its own domain and racing against the other the way real hardware actually does. `test_random_data_integrity` runs this twice, at two clock ratios chosen to not share nice round numbers (`wr_clk=7ns/rd_clk=17ns`, then flipped). A logic bug in the Gray-code arithmetic or the full/empty comparison can easily pass by coincidence at one alignment and fail at another, so running it once at some convenient ratio wouldn't prove much.

### What simulation proves about CDC

Here is what each kind of check covers. Metastability itself is analog: a synchronizer's first flop can settle somewhere invalid before landing one way or the other, and digital simulation updates every register instantaneously, so that effect belongs to circuit-level and structural analysis. The same goes for bit-tearing across a multi-bit bus from per-wire delay mismatches.

What this testbench proves: that the CDC-safe pattern is implemented correctly. Gray coding, two synchronizer stages (not zero, not one), and the specific bit-inversion rule for `full` are all checked under several different clock-frequency relationships. A wrong Gray-code formula or a missing synchronizer stage is exactly the class of bug this catches, and it does (see below). Static CDC analysis tools such as SpyGlass CDC or Conformal CDC look at the structure of the netlist itself (how many flop stages, what combinational logic sits between them) and are the industry-standard next step for sign-off; they are on the roadmap.

**Design note on reset:** this design supports resetting both domains together, which is what the spec calls for. Resetting `wr_rst_n` alone clears the write domain's copy of the synchronized read pointer while the read-domain pointer is untouched, so for a couple of read-domain cycles the two sides can disagree about how much data is there. Supporting an independent single-domain reset would add reset synchronization in each direction; that is a natural extension. `test_simultaneous_dual_domain_reset_mid_stream` tests the supported case.

### Async test results

| Test | What it targets |
|---|---|
| `test_reset_behavior` | Both domains coming out of reset clean, dirtied first — same idea as the sync suite, twice over. |
| `test_single_write_read` | Basic cross-domain integrity. The push and the pop are on genuinely different clocks. |
| `test_fill_to_full` | `full` asserting at exactly `DEPTH` using nothing but a Gray-coded pointer that arrived through a synchronizer. |
| `test_push_when_full` | A push while full corrupting the oldest entry — checked by draining and confirming it afterward. |
| `test_pop_when_empty` | A pop while empty corrupting the read pointer — same check as the sync suite. |
| `test_boundary_depth_minus_one_and_plus_one` | The off-by-one line, across domains this time. |
| `test_simultaneous_dual_domain_reset_mid_stream` | The one reset mode this design actually supports, tested mid-stream rather than from idle. |
| `test_random_data_integrity` | 2,000 transfers at each of two clock ratios, 4,000 total, checked for order, loss, duplication, corruption. |

```
TESTS=8 PASS=8 FAIL=0 SKIP=0
[wr_faster_than_rd] wr_clk=7ns rd_clk=17ns seed=42: 2000 values transferred, 0 lost/corrupted/reordered.
[rd_faster_than_wr] wr_clk=17ns rd_clk=7ns seed=42: 2000 values transferred, 0 lost/corrupted/reordered.
```

### Async coverage

| Corner case | Hit? |
|---|---|
| FIFO reached full | ✅ |
| FIFO reached empty | ✅ |
| Push rejected while full | ✅ |
| Pop rejected while empty | ✅ |
| Data-integrity run, write clock faster | ✅ |
| Data-integrity run, read clock faster | ✅ |
| Both domains reset together mid-stream | ✅ |

7/7. Lands in `results/coverage_async.xml` — that file is cocotb-coverage's whole shared database, so it'll also have the sync suite's bins in whatever state they were left in. Look under `async_fifo_corner_cases` for the async numbers specifically.

### Proving the async tests can fail too

Same idea as the sync section, aimed at the CDC-specific logic this time. Dropped the wrap-bit inversion from `full`'s comparison on purpose — a genuinely common mistake when people implement this algorithm:

```verilog
// BUG (deliberate, for validation): missing the top-bit inversion
wire full_next = (wr_ptr_gray_next == rd_ptr_gray_sync2);
```

Without the inversion, a freshly-reset FIFO (both Gray pointers sitting at 0) reads as immediately full, because 0 == 0. 7 of 8 tests failed right away, and `test_random_data_integrity` caught it with `writer stalled: only pushed 0/200 after 4000 wr_clk cycles -- likely a stuck 'full' flag` — a real, diagnosable message, not a hang with no explanation. That `max_cycles` guard in the writer/reader loops exists for exactly this: a genuinely broken DUT should fail loud with context, not just sit there. Reverted, confirmed clean again.

This pass also turned up a bug in the testbench itself, not the RTL, and fixing it made the suite more trustworthy. An earlier version of the writer coroutine checked its loop-exit condition before the clock edge that would commit the final queued push, so the last transfer's `wr_en` got zeroed before the hardware saw it. The checker's bookkeeping said 200 pushed while the DUT had received 199, and the reader waited forever on a value that was never written. It hung at exactly 199/200 on every seed, which pointed to something structural and not an unlucky roll. The fix restructures the loop so a queued operation's edge always completes before the loop decides whether to stop.

## Formal verification

Random testing, however long you run it, only ever samples the state space. Formal model checking covers all of it, up to whatever depth you check, by asking an SMT solver to prove a property has no counterexample rather than just failing to find one in N random tries. Added this with [SymbiYosys](https://github.com/YosysHQ/sby) (Yosys + Z3), on top of the two directed/random suites above, not instead of them.

### Both formal wrappers are black boxes on purpose

`formal/sync_fifo_formal.sv` and `formal/async_fifo_formal.sv` instantiate the real DUT and check it only through its own ports — `wr_en`, `rd_en`, `full`, `empty`, and so on — never reaching into internal registers like `wr_ptr`. First attempt at the sync wrapper did reach in, through a hierarchical dot-path (`dut.wr_ptr`), and it silently produced a proof with zero actual `$assert` cells in it: Yosys's `prep` flattening restructures the hierarchy in a way that breaks a plain textual dot-path reference, so nothing downstream ever got checked, and a deliberately broken build of the RTL "passed" the proof — vacuously, because nothing was being asked of it. Caught it by explicitly counting assert cells after `prep`, not by the proof failing the way it should have. The fix ended up mirroring `ref_model.py`'s own philosophy: don't trust internal signal names, watch only what's externally observable. Each wrapper carries a small shadow counter that reconstructs the live item count purely from `wr_en`/`rd_en`/`full`/`empty`, then checks it against the DUT's own `full`/`empty` outputs.

### What's proved

For both designs: `full` and `empty` are never simultaneously true, and the live item count never exceeds `DEPTH`. Both run as bounded model checking (`mode bmc`) at depth 16 — a full fill-to-DEPTH-and-drain cycle, exhaustively, not sampled.

Tried `mode prove` (k-induction, technically unbounded) on the sync design first, since it's usually the faster option once it works. Basecase passed; the induction step didn't. That means the four-property set as written isn't self-inductive on its own — there's some hypothetical state that satisfies all four properties but isn't actually reachable from reset, from which the solver can still step to a violation. Fixing that properly means finding and adding the missing auxiliary invariant that rules out that spurious state, which is its own small research problem. Went with a solid depth-16 BMC proof instead rather than leave a broken `mode prove` run in the repo — a real, exhaustive-to-depth-16 proof beats an induction attempt that doesn't actually close.

The async proof needed its own separate fix, for a different reason. First draft of `async_fifo_formal.sv` had its shadow counter written as a single register updated from two separate `always` blocks, one per clock domain — a straightforward multi-driver bug that should never have compiled the way it was reasoned out on paper. Fixed by splitting it into two free-running, single-driver counters (`wr_push_count`, `rd_pop_count`), one per domain, with the live count read as their plain difference.

Second, tried running the async proof with `multiclock on`, treating `wr_clk` and `rd_clk` as genuinely independent free inputs so the solver could explore arbitrary relative edge orderings. That broke reset: these are synchronous resets, so a register only actually clears when its own clock ticks while `rst_n` is held low, and under multiclock unrolling the solver is completely free to just never toggle one of the clocks during the reset window — leaving that domain's registers sitting at arbitrary garbage forever. Confirmed this by dumping the generated counterexample testbench and finding the shadow counters already at nonzero values at step 0, before any clock edge had fired. Real fairness constraints on independently-free clocks are a legitimate way to fix this properly, but getting them right is its own undertaking, so instead the two clocks are tied together in the formal wrapper. That's a real, documented scope reduction — this proof does not explore arbitrary asynchronous relative-phase orderings the way true CDC-aware formal verification would. What it does check, exhaustively, is that the Gray-code pointer logic, the synchronizer stages, and the full/empty comparisons are self-consistent and never overflow, under lockstep clocking. Still catches the same class of control-logic bug (see below); just doesn't claim to explore clock-relative-phase space the way `multiclock on` would if done properly.

### Proving the formal proofs can fail too

Same discipline as the cocotb suites: break the RTL on purpose, confirm the proof catches it, revert, confirm clean.

Sync: reintroduced the missing wrap-bit check in `full`'s comparison. The proof failed at step 2 — barely into the trace, since a freshly-reset FIFO with a broken `full` comparison hits the bug almost immediately.

Async: dropped the top-bit inversion from `full_next`'s comparison, same deliberate bug as the cocotb suite exercises. The proof failed at step 3.

Both reverted, both confirmed clean again afterward.

```bash
cd formal
sby -f sync_fifo.sby     # PASS in ~20s
sby -f async_fifo.sby    # PASS in ~6s
```

## How to run

### Setup (macOS, Homebrew)

```bash
brew install icarus-verilog          # ships native arm64 bottles, no Rosetta needed
brew install python@3.11             # cocotb-coverage needs Python >=3.11, system Python is almost certainly older
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

Verified working together: cocotb 2.1.0, cocotb-coverage 2.0 (needs cocotb>=2.0), Icarus Verilog 13.0 (cocotb wants ≥11.0).

One thing that'll bite you: don't put this repo under a path with a space in the name. GNU Make treats whitespace as a separator when it parses dependency targets, and cocotb's own shipped `Makefile.sim` builds several of its internal targets straight from `$(PWD)`. A space in there breaks the build with "circular dependency" and "no rule to make target" errors that have absolutely nothing to do with your RTL and will send you down the wrong path for a while. Found this the hard way.

### Run everything

```bash
make          # sync FIFO suite: 10 tests, default 5,000-cycle random test
make async    # async FIFO suite: 8 tests, default 2,000 transfers per clock ratio
```

Expected: `TESTS=10 PASS=10 FAIL=0 SKIP=0` for sync, `TESTS=8 PASS=8 FAIL=0 SKIP=0` for async, each ending in a `7/7 corner cases covered` line. Everything lands in `results/`: `results_sync.xml` / `results_async.xml` (JUnit, for CI), `coverage.xml` / `coverage_async.xml`, and `waves.vcd` / `waves_async.vcd` if you want to actually look at the signals in GTKWave.

### Variations

```bash
RANDOM_CYCLES=50000 make                    # sync, longer run for more confidence
ASYNC_RANDOM_TRANSFERS=10000 make async     # same idea, async side
RANDOM_SEED=42 make                          # reproduce a specific sync run
RANDOM_SEED=42 make async                    # same, async
make DEPTH=8 DATA_WIDTH=16                   # run at a different size (DEPTH a power of 2)
make sweep                                   # both suites at depths 4/8/16/32 and widths 8/16
make clean-all                               # wipe results/ and the sim build dirs
```

## Project structure

```
fifo-verification/
├── rtl/
│   ├── sync_fifo.v              # the sync design under test
│   ├── async_fifo.v             # the dual-clock design under test
│   ├── iverilog_dump.v          # VCD dump helper for sync_fifo, Icarus-specific, not part of the design
│   └── iverilog_dump_async.v    # same, for async_fifo
├── verif/
│   ├── test_sync_fifo.py    # 10 cocotb tests (9 directed + 1 randomized), sync
│   ├── test_async_fifo.py   # 8 cocotb tests (7 directed + 1 randomized), async
│   ├── ref_model.py         # RefFifo (sync, cycle-accurate) + OrderedIntegrityChecker (async, order-only)
│   └── coverage.py          # coverage bin definitions for both suites, plus report/export
├── formal/
│   ├── sync_fifo_formal.sv    # black-box formal wrapper + properties for sync_fifo.v
│   ├── sync_fifo.sby          # SymbiYosys job file, sync (BMC, depth 16)
│   ├── async_fifo_formal.sv   # black-box formal wrapper + properties for async_fifo.v
│   └── async_fifo.sby         # SymbiYosys job file, async (BMC, depth 16, tied clocks)
├── Makefile                 # cocotb-driven sim, strict IEEE 1364-2005 (-g2005); `make` = sync, `make async` = async
├── requirements.txt
└── results/                 # generated: per-configuration results_*.xml, coverage{,_async}.xml, waves{,_async}.vcd
```

## What I'd add next

Finish the sync design's k-induction proof (`mode prove`) properly — find and add the auxiliary invariant that makes the four-property set self-inductive, instead of settling for a fixed-depth BMC proof. Would give an actually unbounded guarantee rather than "true up to depth 16."

Real multiclock formal verification for the async design, with proper fairness constraints on independently-free `wr_clk`/`rd_clk` so the solver can explore genuine asynchronous relative-phase orderings instead of the current tied-clock scope reduction.

Static CDC analysis (SpyGlass CDC, Conformal CDC, something in that family) on the async design — the actual industry-standard way to check synchronizer structure and metastability risk, which functional simulation just can't do (see the CDC section above for why).

Verilator as a second simulator. Running the exact same testbenches against two independently-implemented simulators is a good sanity check that a passing result reflects real RTL behavior and not some simulator-specific quirk. Worth doing before trusting this as a final signoff rather than just a development check.

Independent single-domain reset support for the async FIFO, with the extra reset-synchronization machinery that needs (see the design note on reset in the async section above).
