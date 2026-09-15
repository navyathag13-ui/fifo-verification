"""
ref_model.py -- Golden reference model for sync_fifo.v.

A plain Python deque standing in for the FIFO's memory, with two details
modeled precisely to match the RTL bit-for-bit rather than approximately:

1. Registered read latency. `rd_data` in the RTL is a register
   (`rd_data <= mem[rd_addr]`), so a pop issued on cycle N is only
   visible on `dut.rd_data` starting cycle N+1 -- not combinationally on
   cycle N. `RefFifo.rd_data` mirrors that register exactly: it only
   changes inside `step()`, after a successful pop, and holds its value
   on any cycle where no pop happens (matching the RTL's implicit
   register-hold when the `rd_en && !empty` branch isn't taken).

2. Both operations gated against *pre-edge* full/empty. sync_fifo.v's
   write and read logic live in two independent `always @(posedge clk)`
   blocks, each independently gated by the full/empty state as it stood
   *before* this clock edge -- not updated mid-step by the other block's
   effect on the same edge. `step()` reads `full`/`empty` once at the top
   and uses those captured values for both the push and pop decision, so
   a same-cycle push+pop is evaluated exactly like the RTL: as two
   simultaneous decisions against one shared prior state, not a
   push-then-pop or pop-then-push sequence.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass
class StepResult:
    popped: bool          # a pop actually happened this cycle
    pushed: bool          # a push actually happened this cycle
    popped_value: int | None  # the value removed, if popped


class RefFifo:
    def __init__(self, depth: int, data_width: int):
        self.depth = depth
        self._mask = (1 << data_width) - 1
        self._data: deque[int] = deque()
        self.rd_data: int = 0  # mirrors the DUT's registered rd_data output

    @property
    def full(self) -> bool:
        return len(self._data) >= self.depth

    @property
    def empty(self) -> bool:
        return len(self._data) == 0

    @property
    def count(self) -> int:
        return len(self._data)

    def reset(self) -> None:
        self._data.clear()
        self.rd_data = 0

    def step(self, wr_en: bool, wr_data: int, rd_en: bool) -> StepResult:
        """Advance by one clock edge. Call once per cycle, with the same
        wr_en/wr_data/rd_en the DUT was driven with that cycle."""
        was_full = self.full
        was_empty = self.empty

        popped = False
        popped_value = None
        if rd_en and not was_empty:
            popped_value = self._data.popleft()
            self.rd_data = popped_value
            popped = True
        # else: rd_data holds -- no assignment, matching the RTL's
        # implicit register hold when the branch isn't taken.

        pushed = False
        if wr_en and not was_full:
            self._data.append(wr_data & self._mask)
            pushed = True

        return StepResult(popped=popped, pushed=pushed, popped_value=popped_value)


class OrderedIntegrityChecker:
    """
    Golden model for the async FIFO's data-integrity property.

    A cycle-by-cycle full/empty comparison (like RefFifo, above) isn't
    meaningful across two independent, unrelated clocks -- there's no
    shared notion of "this cycle" between wr_clk and rd_clk. What *is*
    meaningful regardless of clock relationship: every value that comes
    out must be the next value, in order, of what went in -- no loss, no
    duplication, no reordering, no corruption. This checker verifies
    exactly that and nothing more, by construction: pushed values queue
    up on one side, popped values are checked against the front of that
    same queue on the other.
    """

    def __init__(self):
        self._expected: deque[int] = deque()
        self.pushed_count = 0
        self.popped_count = 0

    def record_push(self, value: int) -> None:
        self._expected.append(value)
        self.pushed_count += 1

    def check_pop(self, got_value: int) -> None:
        """Call with the value the DUT actually produced for a pop.
        Raises AssertionError with full context if it doesn't match the
        oldest still-unread pushed value."""
        if not self._expected:
            raise AssertionError(
                f"DUT produced a pop (value={got_value:#04x}) but no pushed value "
                f"is still outstanding -- more data came out than ever went in."
            )
        expected_value = self._expected.popleft()
        self.popped_count += 1
        if got_value != expected_value:
            raise AssertionError(
                f"data integrity failure: pop #{self.popped_count} expected "
                f"{expected_value:#04x} (the {self.popped_count}-th value ever pushed), "
                f"got {got_value:#04x}"
            )

    @property
    def outstanding(self) -> int:
        """Values pushed but not yet popped -- what the DUT should
        currently be holding, from the reference's point of view."""
        return len(self._expected)
