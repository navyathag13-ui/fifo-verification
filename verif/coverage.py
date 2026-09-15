"""
coverage.py -- Functional coverage tracking for both FIFO test suites.

Uses cocotb-coverage's CoverPoint primitives -- the same CRV/MDV-style
coverage model SystemVerilog verification environments use -- rather than
a hand-rolled dict, since it's the actively-maintained, ecosystem-standard
tool for cocotb (see README for why this was chosen over hand-rolling it).

Each corner case here is a single-bin hit/miss CoverPoint: "coverage"
means "at least one cycle reached this state during the random test,"
mirroring gcov's line/branch-hit semantics on the software side. This is
deliberately not a value-domain coverage model (no cross-coverage on
specific data values) -- the thing worth proving is that the fuzzing
actually *reached* these states at all, not how many times.
"""

from __future__ import annotations

from cocotb_coverage.coverage import CoverPoint, coverage_db


class CoverageGroup:
    """A named set of single-bin hit/miss CoverPoints, reportable together."""

    def __init__(self, group: str, bin_defs: list[tuple[str, str]]):
        self.group = group
        self._descriptions = dict(bin_defs)
        self.all_bins = [name for name, _ in bin_defs]
        self._samplers = {name: self._make_sampler(f"{group}.{name}") for name in self.all_bins}

    @staticmethod
    def _make_sampler(full_name: str):
        # CoverPoint's implementation unconditionally inspects the first
        # positional argument of the decorated function (it's designed to
        # also work decorating bound methods, and checks for that on the
        # first call), so a truly zero-argument sample function isn't
        # supported -- every sampler here takes one placeholder arg.
        @CoverPoint(full_name, xf=lambda _marker: True, bins=[True])
        def _sample(_marker):
            pass
        return _sample

    def hit(self, bin_name: str) -> None:
        self._samplers[bin_name](True)

    def report(self, log) -> dict:
        results = {}
        log.info("=" * 70)
        log.info(f"FUNCTIONAL COVERAGE REPORT ({self.group})")
        log.info("=" * 70)
        for name in self.all_bins:
            item = coverage_db[f"{self.group}.{name}"]
            was_hit = item.cover_percentage >= 100.0
            results[name] = was_hit
            status = "HIT " if was_hit else "MISS"
            log.info(f"  [{status}] {name:<38} {self._descriptions[name]}")
        n_hit = sum(results.values())
        log.info("-" * 70)
        log.info(f"  {n_hit}/{len(self.all_bins)} corner cases covered")
        log.info("=" * 70)
        return results


# ===========================================================================
# Sync FIFO coverage
# ===========================================================================

_SYNC_BIN_DEFS = [
    ("full_boundary_reached", "FIFO reached full at least once"),
    ("empty_boundary_reached", "FIFO reached empty at least once"),
    ("simultaneous_push_pop_while_full", "wr_en+rd_en asserted together while full"),
    ("simultaneous_push_pop_while_empty", "wr_en+rd_en asserted together while empty"),
    ("reset_while_nonempty", "reset asserted while FIFO held unread data"),
    ("back_to_back_push_then_pop", "a push-only cycle immediately followed by a pop-only cycle"),
    ("multiple_consecutive_resets", "two or more reset cycles asserted back-to-back"),
]
_sync = CoverageGroup("fifo_corner_cases", _SYNC_BIN_DEFS)
ALL_BINS = _sync.all_bins  # kept for backward compatibility


def cover_full_boundary_reached():
    _sync.hit("full_boundary_reached")


def cover_empty_boundary_reached():
    _sync.hit("empty_boundary_reached")


def cover_simultaneous_push_pop_while_full():
    _sync.hit("simultaneous_push_pop_while_full")


def cover_simultaneous_push_pop_while_empty():
    _sync.hit("simultaneous_push_pop_while_empty")


def cover_reset_while_nonempty():
    _sync.hit("reset_while_nonempty")


def cover_back_to_back_push_then_pop():
    _sync.hit("back_to_back_push_then_pop")


def cover_multiple_consecutive_resets():
    _sync.hit("multiple_consecutive_resets")


def report(log) -> dict:
    return _sync.report(log)


def export(path: str = "results/coverage.xml") -> None:
    coverage_db.export_to_xml(filename=path)


# ===========================================================================
# Async FIFO coverage
# ===========================================================================

_ASYNC_BIN_DEFS = [
    ("full_boundary_reached", "FIFO reached full at least once"),
    ("empty_boundary_reached", "FIFO reached empty at least once"),
    ("push_rejected_while_full", "a push was attempted (and rejected) while full"),
    ("pop_rejected_while_empty", "a pop was attempted (and rejected) while empty"),
    ("wr_clk_faster_than_rd_clk", "data-integrity test run with the write clock faster than the read clock"),
    ("rd_clk_faster_than_wr_clk", "data-integrity test run with the read clock faster than the write clock"),
    ("simultaneous_dual_domain_reset", "both wr_clk and rd_clk domains reset together mid-stream"),
]
_async = CoverageGroup("async_fifo_corner_cases", _ASYNC_BIN_DEFS)


def cover_async_full_boundary_reached():
    _async.hit("full_boundary_reached")


def cover_async_empty_boundary_reached():
    _async.hit("empty_boundary_reached")


def cover_async_push_rejected_while_full():
    _async.hit("push_rejected_while_full")


def cover_async_pop_rejected_while_empty():
    _async.hit("pop_rejected_while_empty")


def cover_async_wr_clk_faster_than_rd_clk():
    _async.hit("wr_clk_faster_than_rd_clk")


def cover_async_rd_clk_faster_than_wr_clk():
    _async.hit("rd_clk_faster_than_wr_clk")


def cover_async_simultaneous_dual_domain_reset():
    _async.hit("simultaneous_dual_domain_reset")


def report_async(log) -> dict:
    return _async.report(log)


def export_async(path: str = "results/coverage_async.xml") -> None:
    coverage_db.export_to_xml(filename=path)
