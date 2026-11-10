"""
test_triage_demo.py -- two deliberately faulty tests used only to check
tools/triage.py. They are never part of the normal suite (`make` runs
test_sync_fifo); tools/triage_selftest.sh runs them with MODULE=test_triage_demo.

Each one reproduces a real way test runs go wrong, so the triage tool can be
checked against a known answer:

- test_demo_testbench_bug: a testbench fault that only some seeds reach.
  It pushes random bursts but forgets to check `full`, so when a burst is
  longer than the FIFO the extra pushes are (correctly) dropped by the design
  and the testbench wrongly blames the design. Same failure on every rerun of
  a given seed; passes on other seeds. This is the shape of the real 3-in-8
  seed failure described in the README.

- test_demo_leaky_state: fails when a marker file left behind by an earlier
  run is still there, then cleans it up. The result depends on what ran
  before, not on the seed or the design, so the same seed fails and then
  passes on rerun: a flaky test.
"""

from __future__ import annotations

import os
import random
import tempfile
from pathlib import Path

import cocotb

from test_sync_fifo import clock_edge, get_params, reset_dut, start_clock

MARKER = Path(tempfile.gettempdir()) / "fifo_triage_demo_marker"


@cocotb.test()
async def test_demo_testbench_bug(dut):
    await start_clock(dut)
    await reset_dut(dut)
    depth, data_width = get_params(dut)
    mask = (1 << data_width) - 1
    seed = int(os.environ.get("RANDOM_SEED", "1"))
    rnd = random.Random(seed)
    for burst_no in range(3):
        burst = rnd.randint(1, depth + 2)  # testbench bug: can exceed depth, and `full` is never checked
        pushed = []
        dut.wr_en.value = 1
        for i in range(burst):
            dut.wr_data.value = (burst_no * 64 + i) & mask
            pushed.append((burst_no * 64 + i) & mask)
            await clock_edge(dut)
        dut.wr_en.value = 0
        popped = []
        dut.rd_en.value = 1
        for _ in range(len(pushed)):
            await clock_edge(dut)
            popped.append(int(dut.rd_data.value))
        dut.rd_en.value = 0
        await reset_dut(dut)
        assert popped == pushed, f"burst {burst_no}: pushed {len(pushed)} items, read back a different sequence"


@cocotb.test()
async def test_demo_leaky_state(dut):
    await start_clock(dut)
    await reset_dut(dut)
    if MARKER.exists():
        MARKER.unlink()
        raise AssertionError("state left over from a previous run")
    MARKER.write_text("left behind on purpose")
