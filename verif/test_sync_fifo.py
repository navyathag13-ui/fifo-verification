"""
test_sync_fifo.py -- cocotb testbench for rtl/sync_fifo.v.

Nine directed tests, each targeting a specific, real class of FIFO bug
(see README for the full reasoning), plus one randomized test that
compares the DUT against a plain Python reference model (ref_model.py)
over a long pseudo-random operation sequence, tracking functional
coverage (coverage.py) of the corner cases that traffic is expected to
reach.

A note on `clock_edge()`: every wait for a clock edge in this file goes
through this helper rather than a bare `RisingEdge(dut.clk)`, because on
this toolchain (cocotb 2.1.0 / Icarus 13.0) a coroutine resuming from
`RisingEdge` alone can observe registered outputs *before* that edge's
nonblocking assignments have actually settled -- confirmed empirically by
reading `wr_ptr` and the memory array directly after a push. `ReadOnly()`
is the standard cocotb mechanism for waiting until the current timestep's
value updates have fully applied before reading anything.
"""

from __future__ import annotations

import os
import random
from collections import deque

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadWrite, RisingEdge

import coverage as cov
from ref_model import RefFifo

CLK_PERIOD_NS = 10


async def clock_edge(dut) -> None:
    """Wait for the next rising edge, then for that edge's registered
    updates to actually settle, before returning control to the caller.

    Uses ReadWrite() rather than ReadOnly(): both settle after the RTL's
    nonblocking assignments have applied (confirmed empirically -- on
    this toolchain, reading a registered signal immediately after a bare
    RisingEdge can observe its *pre*-edge value), but ReadOnly() forbids
    driving any signal afterward, which every one of these tests needs
    to do on the very next line (setting up the following cycle's
    inputs). ReadWrite() gives the same settled reads without that
    restriction.
    """
    await RisingEdge(dut.clk)
    await ReadWrite()


def get_params(dut) -> tuple[int, int]:
    return int(dut.DEPTH.value), int(dut.DATA_WIDTH.value)


async def start_clock(dut) -> None:
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, unit="ns").start())


async def reset_dut(dut, cycles: int = 2) -> None:
    dut.rst_n.value = 0
    dut.wr_en.value = 0
    dut.rd_en.value = 0
    dut.wr_data.value = 0
    for _ in range(cycles):
        await clock_edge(dut)
    dut.rst_n.value = 1
    await clock_edge(dut)


# ===========================================================================
# Directed tests
# ===========================================================================

@cocotb.test()
async def test_reset_behavior(dut):
    """A FIFO that doesn't clear empty/full correctly on reset lets stale
    flags mislead every downstream consumer about whether it's safe to
    push or pop -- this is the most basic contract the FIFO makes, and
    everything else assumes it holds. Deliberately dirties the FIFO
    first, so this proves reset actually clears state, not just that a
    freshly-elaborated (all-zero) simulation happens to look right."""
    await start_clock(dut)
    await reset_dut(dut)

    dut.wr_en.value = 1
    for i in range(3):
        dut.wr_data.value = i
        await clock_edge(dut)
    dut.wr_en.value = 0
    assert dut.empty.value == 0, "sanity check failed: FIFO should be non-empty before testing reset"

    await reset_dut(dut)
    assert dut.empty.value == 1, "empty should be asserted immediately after reset"
    assert dut.full.value == 0, "full should be deasserted immediately after reset"


@cocotb.test()
async def test_single_write_read(dut):
    """Confirms basic data integrity end-to-end, accounting for the
    read path's one-cycle registered latency -- the simplest possible
    case, but it's the floor every other test builds on."""
    await start_clock(dut)
    await reset_dut(dut)
    _depth, data_width = get_params(dut)
    test_value = 0xA5 & ((1 << data_width) - 1)

    dut.wr_en.value = 1
    dut.wr_data.value = test_value
    await clock_edge(dut)
    dut.wr_en.value = 0
    assert dut.empty.value == 0, "FIFO should not be empty right after one push"

    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == test_value, f"data integrity failure: wrote {test_value:#x}, read back {got:#x}"
    assert dut.empty.value == 1, "FIFO should be empty again after popping the only item"


@cocotb.test()
async def test_fill_to_full(dut):
    """An off-by-one here either lets the FIFO silently overwrite its
    oldest unread entry (full asserted one cycle late) or wastes a slot
    by asserting full one cycle early -- both are classic, real FIFO
    bugs, not hypothetical ones."""
    await start_clock(dut)
    await reset_dut(dut)
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1

    dut.wr_en.value = 1
    for i in range(depth):
        assert dut.full.value == 0, f"full asserted early, before push {i}/{depth}"
        dut.wr_data.value = i & mask
        await clock_edge(dut)
    dut.wr_en.value = 0
    assert dut.full.value == 1, f"full not asserted after exactly {depth} pushes"


@cocotb.test()
async def test_push_when_full(dut):
    """A push silently accepted while full corrupts the oldest unread
    entry (classic FIFO overflow) instead of cleanly rejecting the
    write -- exactly the kind of bug that only shows up under sustained
    back-pressure, not a light smoke test."""
    await start_clock(dut)
    await reset_dut(dut)
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1

    dut.wr_en.value = 1
    for i in range(depth):
        dut.wr_data.value = i & mask
        await clock_edge(dut)
    assert dut.full.value == 1

    # Attempt a rejected push while full.
    dut.wr_data.value = 0xFF & mask
    await clock_edge(dut)
    dut.wr_en.value = 0
    assert dut.full.value == 1, "FIFO should still report full after a rejected push"

    # Drain and confirm the oldest value (0) wasn't clobbered by the
    # rejected push.
    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == 0, f"oldest entry corrupted by push-while-full: expected 0x00, got {got:#x}"


@cocotb.test()
async def test_pop_when_empty(dut):
    """A pop accepted while empty either returns garbage as if it were
    real data, or worse, corrupts the read pointer so every subsequent
    read is off by one -- a consumer polling an idle FIFO must never be
    able to walk the pointers out of sync with reality."""
    await start_clock(dut)
    await reset_dut(dut)
    assert dut.empty.value == 1

    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.rd_en.value = 0
    assert dut.empty.value == 1, "FIFO should still be empty after a rejected pop"

    # Push one real value and confirm it's still retrievable correctly --
    # proves the read pointer wasn't corrupted by the earlier no-op pop.
    _depth, data_width = get_params(dut)
    test_value = 0x3C & ((1 << data_width) - 1)
    dut.wr_en.value = 1
    dut.wr_data.value = test_value
    await clock_edge(dut)
    dut.wr_en.value = 0

    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == test_value, f"read pointer corrupted by earlier no-op pop: expected {test_value:#x}, got {got:#x}"


@cocotb.test()
async def test_simultaneous_push_pop(dut):
    """Push and pop sharing a clock edge is exactly the kind of race a
    counter-based fill-tracking implementation gets wrong (incrementing
    and decrementing one shared counter in the same cycle is easy to get
    backwards). A pointer-based design handles it for free -- push and
    pop touch independent pointers -- but only if both always blocks are
    wired to their own independent full/empty gating, not a shared one
    that could see a half-updated state."""
    await start_clock(dut)
    await reset_dut(dut)
    _depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1

    # Seed with one item so the FIFO is neither full nor empty.
    dut.wr_en.value = 1
    dut.wr_data.value = 0x11 & mask
    await clock_edge(dut)

    # Drive wr_en and rd_en together on the same cycle.
    dut.wr_data.value = 0x22 & mask
    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.wr_en.value = 0
    dut.rd_en.value = 0

    got = int(dut.rd_data.value)
    assert got == (0x11 & mask), f"simultaneous pop returned wrong data: expected 0x11, got {got:#x}"
    assert dut.empty.value == 0, "simultaneous push+pop should leave exactly one item (0x22) resident"
    assert dut.full.value == 0

    # Drain and confirm the simultaneous push really landed.
    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == (0x22 & mask), f"simultaneous push was lost: expected 0x22, got {got:#x}"
    assert dut.empty.value == 1


@cocotb.test()
async def test_reset_mid_transaction(dut):
    """Reset must be an unconditional clear, not a bit that happens to
    look clear until the next unrelated write walks a stale pointer
    forward. This specifically guards against a *partial* reset -- e.g.
    one that clears wr_ptr but leaves rd_ptr stale -- which a reset
    tested only from a clean idle state would never expose."""
    await start_clock(dut)
    await reset_dut(dut)
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1

    dut.wr_en.value = 1
    for i in range(max(1, depth // 2)):
        dut.wr_data.value = i & mask
        await clock_edge(dut)
    dut.wr_en.value = 0
    assert dut.empty.value == 0

    await reset_dut(dut)
    assert dut.empty.value == 1
    assert dut.full.value == 0

    # No stale data should leak through: push one new value and confirm
    # it -- and only it -- comes back out.
    test_value = 0x7E & mask
    dut.wr_en.value = 1
    dut.wr_data.value = test_value
    await clock_edge(dut)
    dut.wr_en.value = 0

    dut.rd_en.value = 1
    await clock_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == test_value, f"stale pre-reset data leaked through: expected {test_value:#x}, got {got:#x}"
    assert dut.empty.value == 1, "exactly one item should have been resident post-reset, nothing extra"


@cocotb.test()
async def test_back_to_back_single_cycle(dut):
    """Sustained push+pop every cycle, one slot resident throughout, is
    the steady-state traffic pattern a FIFO sees in a real pipeline. A
    pointer wraparound bug or an off-by-one in the address computation
    surfaces here as data corruption long before it would in a handful
    of directed pushes -- this sequence wraps the pointer address space
    several times over."""
    await start_clock(dut)
    await reset_dut(dut)
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1
    n_cycles = depth * 4

    dut.wr_en.value = 1
    dut.wr_data.value = 0
    await clock_edge(dut)

    expected = deque([0])
    for cycle in range(1, n_cycles + 1):
        wr_val = cycle & mask
        dut.wr_data.value = wr_val
        dut.rd_en.value = 1
        expected.append(wr_val)
        popped_expected = expected.popleft()
        await clock_edge(dut)
        got = int(dut.rd_data.value)
        assert got == popped_expected, f"cycle {cycle}: expected {popped_expected:#x}, got {got:#x}"
    dut.wr_en.value = 0
    dut.rd_en.value = 0


@cocotb.test()
async def test_boundary_depth_minus_one_and_plus_one(dut):
    """The exact boundary is where off-by-one bugs live: DEPTH-1 items
    must not report full, exactly DEPTH must, and a rejected DEPTH+1th
    push must leave the FIFO in exactly the same state as a clean fill
    to DEPTH -- not full, not empty, not corrupted."""
    await start_clock(dut)
    await reset_dut(dut)
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1

    dut.wr_en.value = 1
    for i in range(depth - 1):
        dut.wr_data.value = i & mask
        await clock_edge(dut)
    assert dut.full.value == 0, f"full asserted at DEPTH-1 ({depth - 1}) items"
    assert dut.empty.value == 0

    dut.wr_data.value = (depth - 1) & mask
    await clock_edge(dut)
    assert dut.full.value == 1, f"full not asserted at exactly DEPTH ({depth}) items"

    dut.wr_data.value = 0xAA & mask
    await clock_edge(dut)
    dut.wr_en.value = 0
    assert dut.full.value == 1, "FIFO should still report full after a rejected DEPTH+1 push"

    dut.rd_en.value = 1
    for i in range(depth):
        await clock_edge(dut)
        got = int(dut.rd_data.value)
        assert got == (i & mask), f"item {i}: expected {i & mask:#x}, got {got:#x} -- rejected push corrupted data"
    dut.rd_en.value = 0
    assert dut.empty.value == 1, f"FIFO should be empty after draining exactly {depth} items"


# ===========================================================================
# Randomized, reference-model-driven test
# ===========================================================================

@cocotb.test()
async def test_random_traffic(dut):
    """Drives a long pseudo-random push/pop/reset sequence and compares
    every cycle's observable DUT outputs against a plain Python
    reference model (ref_model.py) -- the same coverage-guided fuzzing
    philosophy as AFL++, applied to RTL: don't just check the cases you
    thought of, throw a long randomized sequence at the design and let a
    trusted oracle catch whatever a directed test missed. Any mismatch
    fails immediately with the exact cycle and recent operation history,
    the same way a minimized fuzzing crash report would.
    """
    await start_clock(dut)
    depth, data_width = get_params(dut)
    n_cycles = int(os.environ.get("RANDOM_CYCLES", "5000"))
    seed = int(os.environ.get("RANDOM_SEED", "0")) or random.randrange(2**32)
    rnd = random.Random(seed)
    dut._log.info(f"test_random_traffic: seed={seed}, cycles={n_cycles}, depth={depth}, data_width={data_width}")

    ref = RefFifo(depth, data_width)
    history = deque(maxlen=20)

    await reset_dut(dut)
    ref.reset()

    consecutive_resets = 0
    prev_was_push_only = False

    # Traffic comes in phases so the rare corners (full, then push+pop while full) are
    # reached under every seed, not just lucky ones. A flat 50/50 push/pop mix on a
    # 16-deep FIFO almost never sits at full long enough to see a simultaneous
    # push+pop there; measured before this change, roughly 3 in 8 random seeds missed it.
    PHASE_PROFILES = [(0.5, 0.5), (0.85, 0.25), (0.25, 0.85), (0.9, 0.9)]
    PHASE_LEN = 100
    p_wr, p_rd = PHASE_PROFILES[0]

    for cycle in range(1, n_cycles + 1):
        if (cycle - 1) % PHASE_LEN == 0:
            p_wr, p_rd = rnd.choice(PHASE_PROFILES)
        # Resets arrive in bursts: right after one, another is far likelier. Independent 2% resets
        # would only give back-to-back resets about 0.04% of the time, so some seeds never saw one.
        do_reset = rnd.random() < (0.25 if consecutive_resets > 0 else 0.02)
        wr_en = False if do_reset else rnd.random() < p_wr
        rd_en = False if do_reset else rnd.random() < p_rd
        wr_data = rnd.randrange(0, 1 << data_width) if wr_en else 0

        was_full = ref.full
        was_empty = ref.empty

        if do_reset:
            dut.rst_n.value = 0
            dut.wr_en.value = 0
            dut.rd_en.value = 0
            await clock_edge(dut)
            dut.rst_n.value = 1

            if not was_empty:
                cov.cover_reset_while_nonempty()
            consecutive_resets += 1
            if consecutive_resets >= 2:
                cov.cover_multiple_consecutive_resets()
            ref.reset()
            history.append(f"cycle {cycle}: RESET")
            prev_was_push_only = False
            continue

        consecutive_resets = 0

        # Coverage sampling uses state as of *before* this cycle's edge --
        # exactly what the DUT's full/empty reflect right now, and exactly
        # the state that gates whether this cycle's push/pop will succeed.
        if wr_en and rd_en and was_full:
            cov.cover_simultaneous_push_pop_while_full()
        if wr_en and rd_en and was_empty:
            cov.cover_simultaneous_push_pop_while_empty()
        if was_full:
            cov.cover_full_boundary_reached()
        if was_empty:
            cov.cover_empty_boundary_reached()
        if prev_was_push_only and rd_en and not wr_en:
            cov.cover_back_to_back_push_then_pop()

        dut.wr_en.value = 1 if wr_en else 0
        dut.wr_data.value = wr_data
        dut.rd_en.value = 1 if rd_en else 0

        result = ref.step(wr_en, wr_data, rd_en)
        await clock_edge(dut)

        dut_full = bool(dut.full.value)
        dut_empty = bool(dut.empty.value)
        dut_rd_data = int(dut.rd_data.value)

        history.append(
            f"cycle {cycle}: wr_en={int(wr_en)} wr_data={wr_data:#04x} rd_en={int(rd_en)} "
            f"-> DUT(full={int(dut_full)},empty={int(dut_empty)},rd_data={dut_rd_data:#04x}) "
            f"REF(full={int(ref.full)},empty={int(ref.empty)})"
        )

        mismatches = []
        if dut_full != ref.full:
            mismatches.append(f"full: DUT={dut_full} REF={ref.full}")
        if dut_empty != ref.empty:
            mismatches.append(f"empty: DUT={dut_empty} REF={ref.empty}")
        if result.popped and dut_rd_data != result.popped_value:
            mismatches.append(f"rd_data: DUT={dut_rd_data:#04x} REF={result.popped_value:#04x}")

        if mismatches:
            lines = [
                "",
                "=" * 78,
                "RANDOM TRAFFIC TEST FAILURE -- minimized reproduction context",
                "=" * 78,
                f"Seed:              {seed}",
                f"Failed at cycle:   {cycle} / {n_cycles}",
                f"Mismatches:        {'; '.join(mismatches)}",
                "",
                "Last operations leading to failure (oldest first):",
            ] + [f"  {h}" for h in history] + ["=" * 78]
            full_report = "\n".join(lines)
            dut._log.error(full_report)
            assert False, full_report

        prev_was_push_only = wr_en and not rd_en

    dut.wr_en.value = 0
    dut.rd_en.value = 0

    coverage_results = cov.report(dut._log)
    cov.export(path=os.environ.get("COVERAGE_XML", "results/coverage.xml"))
    missed = [name for name, hit in coverage_results.items() if not hit]
    assert not missed, (
        f"Random test ran {n_cycles} cycles but never exercised: {missed}. "
        f"Increase RANDOM_CYCLES or adjust the operation-mix probabilities in this test."
    )
