# Parameterized FIFO Verification Suite (Sync + Async) — cocotb

Two parameterized FIFOs in Verilog, one single-clock, one dual-clock (async), both verified with Python-based [cocotb](https://www.cocotb.org/) testbenches. Same philosophy I apply on the software side: fuzz until it stops finding anything, track coverage so you actually know the fuzzing reached the interesting states, and write tests that assume the design is broken rather than tests that just confirm it isn't. The FIFOs themselves aren't the hard part — pointers, a comparator, a memory array. The verification is the actual project here. Directed tests for the specific ways FIFOs break in practice, randomized tests that check the DUT against a plain Python reference model instead of a fixed list of expected inputs, and for the async design, the thing that actually makes async FIFOs a respected skill: clock-domain-crossing correctness, not just the FIFO logic sitting on top of it.

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

| Corner case | Hit? | Times hit (seed 42, 5,000 cycles) |
|---|---|---|
| FIFO reached full | ✅ | 17 |
| FIFO reached empty | ✅ | 752 |
| Simultaneous push+pop while full | ✅ | 6 |
| Simultaneous push+pop while empty | ✅ | 174 |
| Reset while non-empty | ✅ | 92 |
| Back-to-back push-then-pop | ✅ | 309 |
| Multiple consecutive resets | ✅ | 1 |

7/7. With DEPTH=16, a 50/50 push/pop mix and a 2% reset chance, full-boundary and simultaneous-while-full are the rare ones — you need a real streak of net pushes to get 16 items resident. Which is why the default is 5,000 cycles and not a couple hundred; at 200 cycles those two bins reliably come up empty. Full XML report lands in `results/coverage.xml` after every run.

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

### What simulation can and can't actually prove about CDC

Worth being careful here, because it's an easy spot to oversell. RTL simulation cannot reproduce metastability. A synchronizer's first flop failing to resolve in time is an analog thing — the flip-flop's output settles somewhere invalid before eventually landing one way or the other. Digital simulation doesn't have a concept of "resolving late"; every register update is instantaneous. Same story for bit-tearing across a multi-bit bus from per-wire delay mismatches — also fundamentally analog, also not something zero-delay simulation can show you.

What this testbench does prove: that the CDC-safe pattern itself is implemented correctly. Gray coding, two synchronizer stages (not zero, not one), the specific bit-inversion rule for `full`, all checked under several different clock-frequency relationships. That's real and it's useful, but it's not the same claim as "the silicon will never metastably fail." A wrong Gray-code formula or a missing sync stage is exactly the class of bug this catches, and it does (see below). Proving the actual absence of metastability risk in the implemented pattern is a job for static CDC analysis tools — SpyGlass CDC, Conformal CDC, that kind of thing — which look at the structure of the netlist itself (how many flop stages, any combinational logic sitting between them) instead of simulating it. That's the real industry-standard way to sign off on this, and it's explicitly not something this project does.

One more limitation worth stating plainly: this design only supports resetting both domains together. Reset `wr_rst_n` on its own and it clears the write domain's copy of the synchronized read pointer along with everything else on that side, but the actual read-domain pointer is untouched — so for a couple of read-domain cycles the two sides can disagree about how much data is really there. A design meant to survive an independent single-domain reset needs more machinery than this (each domain's reset synchronized into and propagated to the other), which isn't built here since the spec treats both-domains-together as the supported case. `test_simultaneous_dual_domain_reset_mid_stream` tests exactly that. Independent single-domain reset isn't tested because it isn't claimed to work.

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

While I was at it, this pass also turned up a real bug in the testbench itself, not the RTL, which is worth admitting rather than glossing over. An earlier version of the writer coroutine checked its loop-exit condition before the clock edge that would actually commit the final queued push — so the last transfer's `wr_en` got zeroed before the hardware ever saw it. The checker's bookkeeping said 200 pushed; the DUT had only actually gotten 199; the reader sat there forever waiting on a value that was never really written. I noticed because it hung at exactly 199/200 every time regardless of seed, which is a pretty strong sign something structural was wrong rather than a rare unlucky roll. Fixed by restructuring the loop so a queued operation's edge always completes before the loop decides whether to stop.

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
make clean-all                               # wipe results/ and the sim build dir
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
├── Makefile                 # cocotb-driven sim, strict IEEE 1364-2005 (-g2005); `make` = sync, `make async` = async
├── requirements.txt
└── results/                 # generated: results_{sync,async}.xml, coverage{,_async}.xml, waves{,_async}.vcd
```

## What I'd add next

Formal verification with SymbiYosys, for both designs' full/empty logic — proving things like "full and empty are never both true" and "the live item count never exceeds DEPTH" exhaustively instead of just probabilistically through random testing. Random testing makes a property likely true across whatever sequences it happened to generate. A formal solver proves it for every reachable state, in seconds, for control logic this small. In progress right now, actually.

Static CDC analysis (SpyGlass CDC, Conformal CDC, something in that family) on the async design — the actual industry-standard way to check synchronizer structure and metastability risk, which functional simulation just can't do (see the CDC section above for why).

Verilator as a second simulator. Running the exact same testbenches against two independently-implemented simulators is a good sanity check that a passing result reflects real RTL behavior and not some simulator-specific quirk. Worth doing before trusting this as a final signoff rather than just a development check.

Independent single-domain reset support for the async FIFO, with the extra reset-synchronization machinery that actually needs (see the limitation noted in the async section above).
