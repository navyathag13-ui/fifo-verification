"""
test_async_fifo.py -- cocotb testbench for rtl/async_fifo.v.

Structurally different from test_sync_fifo.py, and deliberately so: with
two independent clocks there's no shared notion of "this cycle" to
compare a reference model against step-by-step. The write side and read
side each run as their own coroutine, driven by their own clock, and the
thing actually being verified is data integrity across the crossing
(ref_model.OrderedIntegrityChecker) plus the same push/pop/boundary
safety properties the sync suite checks -- now under multiple, sometimes
deliberately mismatched, clock relationships.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ReadWrite, RisingEdge

import coverage as cov
from ref_model import OrderedIntegrityChecker


def get_params(dut) -> tuple[int, int]:
    return int(dut.DEPTH.value), int(dut.DATA_WIDTH.value)


async def wr_edge(dut) -> None:
    await RisingEdge(dut.wr_clk)
    await ReadWrite()


async def rd_edge(dut) -> None:
    await RisingEdge(dut.rd_clk)
    await ReadWrite()


def start_clocks(dut, wr_period_ns: float, rd_period_ns: float):
    """Starts both clocks and returns their Tasks. cocotb doesn't kill
    background tasks between @cocotb.test() functions (or between
    scenarios run back-to-back in the same test), and this file
    deliberately runs the *same* wr_clk/rd_clk signals at different
    periods across scenarios -- leaving an old Clock task running would
    mean two independent processes driving one signal with mismatched
    periods, a real contention bug, not a cleanup nicety. Callers must
    kill both tasks when done with them."""
    wr_task = cocotb.start_soon(Clock(dut.wr_clk, wr_period_ns, unit="ns").start())
    rd_task = cocotb.start_soon(Clock(dut.rd_clk, rd_period_ns, unit="ns").start())
    return wr_task, rd_task


def stop_clocks(*tasks) -> None:
    for t in tasks:
        t.cancel()


async def reset_both(dut, cycles: int = 4) -> None:
    """Resets both domains. Since wr_clk and rd_clk are independent,
    each domain's reset has to be pumped by its own clock -- a single
    sequential await-chain (as the sync FIFO's reset_dut uses) would
    silently only ever advance one domain."""
    dut.wr_rst_n.value = 0
    dut.rd_rst_n.value = 0
    dut.wr_en.value = 0
    dut.wr_data.value = 0
    dut.rd_en.value = 0

    async def pump_wr():
        for _ in range(cycles):
            await RisingEdge(dut.wr_clk)

    async def pump_rd():
        for _ in range(cycles):
            await RisingEdge(dut.rd_clk)

    wr_pump = cocotb.start_soon(pump_wr())
    rd_pump = cocotb.start_soon(pump_rd())
    await wr_pump
    await rd_pump

    dut.wr_rst_n.value = 1
    dut.rd_rst_n.value = 1
    await wr_edge(dut)
    await rd_edge(dut)


# ===========================================================================
# Directed tests
# ===========================================================================

@cocotb.test()
async def test_reset_behavior(dut):
    """Same reasoning as the sync suite's version, doubled: both domains
    must independently come out of reset clean, and a reset asserted on
    both must leave the FIFO in a state where the read side sees `empty`
    and the write side sees `!full`, regardless of what was pushed
    beforehand."""
    wr_clk, rd_clk = start_clocks(dut, 10, 10)
    await reset_both(dut)

    dut.wr_en.value = 1
    for i in range(3):
        dut.wr_data.value = i
        await wr_edge(dut)
    dut.wr_en.value = 0

    await reset_both(dut)
    assert dut.empty.value == 1, "empty should be asserted immediately after reset"
    assert dut.full.value == 0, "full should be deasserted immediately after reset"

    stop_clocks(wr_clk, rd_clk)


@cocotb.test()
async def test_single_write_read(dut):
    """Basic cross-domain data integrity, accounting for the read path's
    registered latency -- the async equivalent of the sync suite's
    simplest case, but now the push and the pop are on genuinely
    different clocks."""
    _depth, data_width = get_params(dut)
    test_value = 0xA5 & ((1 << data_width) - 1)
    wr_clk, rd_clk = start_clocks(dut, 10, 13)
    await reset_both(dut)

    dut.wr_en.value = 1
    dut.wr_data.value = test_value
    await wr_edge(dut)
    dut.wr_en.value = 0

    # Give the write pointer's Gray code time to cross the 2-flop
    # synchronizer into the read domain before expecting `empty` to drop.
    for _ in range(4):
        await rd_edge(dut)
        if dut.empty.value == 0:
            break
    assert dut.empty.value == 0, "empty never deasserted after a push -- synchronizer path broken"

    dut.rd_en.value = 1
    await rd_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == test_value, f"data integrity failure across domains: wrote {test_value:#x}, read back {got:#x}"

    stop_clocks(wr_clk, rd_clk)


@cocotb.test()
async def test_fill_to_full(dut):
    """Fills using only the write clock (read side idle) -- confirms
    `full` asserts at exactly DEPTH resident items even though the only
    thing telling the write domain how many items are outstanding is a
    Gray-coded pointer that arrived through a synchronizer, not a direct
    view of the read side's state."""
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1
    wr_clk, rd_clk = start_clocks(dut, 10, 10)
    await reset_both(dut)

    dut.wr_en.value = 1
    for i in range(depth):
        assert dut.full.value == 0, f"full asserted early, before push {i}/{depth}"
        dut.wr_data.value = i & mask
        await wr_edge(dut)
    dut.wr_en.value = 0
    assert dut.full.value == 1, f"full not asserted after exactly {depth} pushes"

    stop_clocks(wr_clk, rd_clk)


@cocotb.test()
async def test_push_when_full(dut):
    """A push accepted while full corrupts the oldest unread entry --
    same reasoning as the sync suite, checked the same way: fill, attempt
    one more, then confirm the oldest value is still intact after
    draining."""
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1
    wr_clk, rd_clk = start_clocks(dut, 10, 10)
    await reset_both(dut)

    dut.wr_en.value = 1
    for i in range(depth):
        dut.wr_data.value = i & mask
        await wr_edge(dut)
    assert dut.full.value == 1

    dut.wr_data.value = 0xFF & mask
    await wr_edge(dut)
    dut.wr_en.value = 0
    assert dut.full.value == 1, "FIFO should still report full after a rejected push"

    # FIFO is already known full (non-empty) here -- no synchronizer
    # settling wait needed, unlike right after the very first push to an
    # idle FIFO. A single edge is exactly one pop.
    dut.rd_en.value = 1
    await rd_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == 0, f"oldest entry corrupted by push-while-full: expected 0x00, got {got:#x}"

    stop_clocks(wr_clk, rd_clk)


@cocotb.test()
async def test_pop_when_empty(dut):
    """A pop accepted while empty either returns garbage or corrupts the
    read pointer -- checked by popping while empty, then confirming a
    real subsequent push/pop still lands correctly."""
    _depth, data_width = get_params(dut)
    test_value = 0x3C & ((1 << data_width) - 1)
    wr_clk, rd_clk = start_clocks(dut, 10, 10)
    await reset_both(dut)
    assert dut.empty.value == 1

    dut.rd_en.value = 1
    await rd_edge(dut)
    dut.rd_en.value = 0
    assert dut.empty.value == 1, "FIFO should still be empty after a rejected pop"

    dut.wr_en.value = 1
    dut.wr_data.value = test_value
    await wr_edge(dut)
    dut.wr_en.value = 0

    for _ in range(4):
        await rd_edge(dut)
        if dut.empty.value == 0:
            break
    assert dut.empty.value == 0, "empty never deasserted after a push -- synchronizer path broken"

    dut.rd_en.value = 1
    await rd_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == test_value, f"read pointer corrupted by earlier no-op pop: expected {test_value:#x}, got {got:#x}"

    stop_clocks(wr_clk, rd_clk)


@cocotb.test()
async def test_boundary_depth_minus_one_and_plus_one(dut):
    """The exact off-by-one boundary, same as the sync suite: DEPTH-1
    must not report full, exactly DEPTH must, and a rejected DEPTH+1th
    push must leave every already-written value intact."""
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1
    wr_clk, rd_clk = start_clocks(dut, 10, 10)
    await reset_both(dut)

    dut.wr_en.value = 1
    for i in range(depth - 1):
        dut.wr_data.value = i & mask
        await wr_edge(dut)
    assert dut.full.value == 0, f"full asserted at DEPTH-1 ({depth - 1}) items"

    dut.wr_data.value = (depth - 1) & mask
    await wr_edge(dut)
    assert dut.full.value == 1, f"full not asserted at exactly DEPTH ({depth}) items"

    dut.wr_data.value = 0xAA & mask
    await wr_edge(dut)
    dut.wr_en.value = 0
    assert dut.full.value == 1, "FIFO should still report full after a rejected DEPTH+1 push"

    # FIFO is already known full here -- no synchronizer settling wait
    # needed, one edge per pop.
    dut.rd_en.value = 1
    for i in range(depth):
        await rd_edge(dut)
        got = int(dut.rd_data.value)
        assert got == (i & mask), f"item {i}: expected {i & mask:#x}, got {got:#x} -- rejected push corrupted data"
    dut.rd_en.value = 0

    stop_clocks(wr_clk, rd_clk)


@cocotb.test()
async def test_simultaneous_dual_domain_reset_mid_stream(dut):
    """Resetting *both* domains together mid-stream -- the safe, common
    case -- must return the FIFO to a clean state with no stale data
    leaking through. (Resetting only one domain independently is a
    separate, genuinely harder problem -- see the README's CDC section
    for why that's explicitly out of scope for this design.)"""
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1
    wr_clk, rd_clk = start_clocks(dut, 10, 13)
    await reset_both(dut)

    dut.wr_en.value = 1
    for i in range(max(1, depth // 2)):
        dut.wr_data.value = i & mask
        await wr_edge(dut)
    dut.wr_en.value = 0

    cov.cover_async_simultaneous_dual_domain_reset()
    await reset_both(dut)
    assert dut.empty.value == 1
    assert dut.full.value == 0

    test_value = 0x7E & mask
    dut.wr_en.value = 1
    dut.wr_data.value = test_value
    await wr_edge(dut)
    dut.wr_en.value = 0

    for _ in range(4):
        await rd_edge(dut)
        if dut.empty.value == 0:
            break
    assert dut.empty.value == 0, "empty never deasserted after a push -- synchronizer path broken"

    dut.rd_en.value = 1
    await rd_edge(dut)
    dut.rd_en.value = 0
    got = int(dut.rd_data.value)
    assert got == test_value, f"stale pre-reset data leaked through: expected {test_value:#x}, got {got:#x}"

    stop_clocks(wr_clk, rd_clk)


# ===========================================================================
# Randomized cross-clock data-integrity test
# ===========================================================================

async def _run_random_integrity_scenario(dut, wr_period_ns, rd_period_ns, n_transfers, seed, scenario_name):
    """Runs one randomized push/pop scenario at a fixed clock-period pair
    and returns the OrderedIntegrityChecker used, fully drained.
    Independent writer and reader coroutines, each on their own clock,
    are the only way to legitimately drive two async-domain signals --
    a single sequential coroutine (as in the sync suite) can't represent
    two unrelated clocks at once."""
    depth, data_width = get_params(dut)
    rnd = random.Random(seed)
    checker = OrderedIntegrityChecker()
    max_cycles = max(200, n_transfers * 20)  # generous deadlock guard

    async def writer():
        # NOTE: the loop deliberately awaits the clock edge *before*
        # checking whether to stop -- not after driving a decision.
        # Recording a push in `checker` marks it as "queued for the next
        # edge," not yet real; checking the exit condition ahead of that
        # edge (as an earlier version of this test did) let the very
        # last push's wr_en get zeroed out before it was ever actually
        # clocked in, silently dropping it while the checker's own
        # bookkeeping still thought it had gone through.
        dut.wr_en.value = 0
        cycles = 0
        while True:
            await wr_edge(dut)
            cycles += 1
            assert cycles < max_cycles, (
                f"[{scenario_name}] writer stalled: only pushed {checker.pushed_count}/{n_transfers} "
                f"after {max_cycles} wr_clk cycles -- likely a stuck `full` flag."
            )
            if checker.pushed_count >= n_transfers:
                dut.wr_en.value = 0
                break
            was_full = bool(dut.full.value)
            if was_full:
                cov.cover_async_full_boundary_reached()
            want_push = rnd.random() < 0.7
            if want_push and not was_full:
                value = rnd.randrange(0, 1 << data_width)
                dut.wr_en.value = 1
                dut.wr_data.value = value
                checker.record_push(value)
            elif want_push and was_full:
                cov.cover_async_push_rejected_while_full()
                dut.wr_en.value = 1
                dut.wr_data.value = rnd.randrange(0, 1 << data_width)
            else:
                dut.wr_en.value = 0

    async def reader():
        dut.rd_en.value = 0
        pending_pop = False
        cycles = 0
        while checker.popped_count < n_transfers:
            cycles += 1
            assert cycles < max_cycles, (
                f"[{scenario_name}] reader stalled: only popped {checker.popped_count}/{n_transfers} "
                f"after {max_cycles} rd_clk cycles -- likely a stuck `empty` flag or lost data."
            )
            await rd_edge(dut)
            if pending_pop:
                checker.check_pop(int(dut.rd_data.value))
                pending_pop = False
            was_empty = bool(dut.empty.value)
            if was_empty:
                cov.cover_async_empty_boundary_reached()
            want_pop = rnd.random() < 0.7
            if want_pop and not was_empty:
                dut.rd_en.value = 1
                pending_pop = True
            else:
                if want_pop and was_empty:
                    cov.cover_async_pop_rejected_while_empty()
                dut.rd_en.value = 0
        dut.rd_en.value = 0

    writer_task = cocotb.start_soon(writer())
    reader_task = cocotb.start_soon(reader())
    await writer_task
    await reader_task

    assert checker.outstanding == 0, (
        f"[{scenario_name}] {checker.outstanding} value(s) pushed but never popped "
        f"-- reader finished without draining everything the writer sent."
    )
    dut._log.info(
        f"[{scenario_name}] wr_clk={wr_period_ns}ns rd_clk={rd_period_ns}ns seed={seed}: "
        f"{checker.pushed_count} values transferred, 0 lost/corrupted/reordered."
    )
    return checker


@cocotb.test()
async def test_random_data_integrity(dut):
    """The core CDC stress test: drives a long randomized push/pop
    sequence and checks the *ordered sequence* of values that come out
    against the *ordered sequence* pushed in (ref_model.OrderedIntegrityChecker)
    -- the only thing that's meaningfully comparable across two
    independent, unrelated clocks, the same way AFL++-style
    coverage-guided fuzzing checks program behavior against an oracle
    rather than a fixed input list.

    Run twice, deliberately at two different (and deliberately
    non-integer-related) clock period ratios: write faster than read,
    then read faster than write. A logic bug in the Gray-code pointer
    arithmetic or the full/empty comparison is exactly the kind of thing
    that can pass at one clock ratio (by coincidence of alignment) and
    fail at another -- which is why this doesn't just run once at a
    single convenient ratio.
    """
    n_transfers = int(os.environ.get("ASYNC_RANDOM_TRANSFERS", "2000"))
    seed = int(os.environ.get("RANDOM_SEED", "0")) or random.randrange(2**32)

    scenarios = [
        ("wr_faster_than_rd", 7, 17),
        ("rd_faster_than_wr", 17, 7),
    ]

    for name, wr_period, rd_period in scenarios:
        if wr_period < rd_period:
            cov.cover_async_wr_clk_faster_than_rd_clk()
        elif rd_period < wr_period:
            cov.cover_async_rd_clk_faster_than_wr_clk()
        wr_clk, rd_clk = start_clocks(dut, wr_period, rd_period)
        await reset_both(dut)
        await _run_random_integrity_scenario(dut, wr_period, rd_period, n_transfers, seed, name)
        stop_clocks(wr_clk, rd_clk)

    coverage_results = cov.report_async(dut._log)
    cov.export_async(path=os.environ.get("COVERAGE_ASYNC_XML", "results/coverage_async.xml"))
    missed = [name for name, hit in coverage_results.items() if not hit]
    assert not missed, (
        f"Random data-integrity test ran but never exercised: {missed}. "
        f"Increase ASYNC_RANDOM_TRANSFERS or adjust the operation-mix probabilities."
    )
