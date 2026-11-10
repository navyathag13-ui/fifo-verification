#!/usr/bin/env bash
# Checks tools/triage.py against three runs whose right answer is known:
#   1. the real suite on the real design      -> nothing fails          (exit 0)
#   2. the real suite on a planted RTL bug    -> fails on every seed    (exit 1)
#      (the full flag ignores the wrap bit, so a full FIFO looks empty)
#   3. test_triage_demo                        -> testbench bug fails on some seeds,
#                                                leaky-state test is flaky
set -uo pipefail
cd "$(dirname "$0")/.."
SEEDS=${SEEDS:-8}
fail=0
check() { if [ "$1" = "$2" ]; then echo "  ok: $3"; else echo "  FAIL: $3 (got $1, want $2)"; fail=1; fi; }
verdicts() { python3 -c "import json,sys; r=json.load(open(sys.argv[1]))['rows']; print(' '.join(sorted(f\"{x['test']}={x['verdict'].replace(' ','_')}\" for x in r)))" "$1"; }

echo "== 1. real design"
python3 tools/triage.py --seeds "$SEEDS" --out results/triage_selftest/clean >/dev/null; check $? 0 "clean suite exits 0"

echo "== 2. planted RTL bug (full flag ignores wrap bit)"
tmp=$(mktemp -d); cp -r . "$tmp/repo"; rm -rf "$tmp/repo"/results/sim_build_*
sed -i.bak 's/assign full  = (wr_addr == rd_addr) \&\& (wr_ptr\[ADDR_WIDTH\] != rd_ptr\[ADDR_WIDTH\]);/assign full  = (wr_addr == rd_addr);/' "$tmp/repo/rtl/sync_fifo.v"
grep -q 'assign full  = (wr_addr == rd_addr);' "$tmp/repo/rtl/sync_fifo.v" || { echo "  FAIL: could not plant bug"; exit 1; }
python3 "$tmp/repo/tools/triage.py" --seeds "$SEEDS" --reruns 1 --out "$PWD/results/triage_selftest/bug" >/dev/null; check $? 1 "planted bug exits 1"
v=$(verdicts results/triage_selftest/bug/triage_report.json); echo "  $v"
case "$v" in *fails_on_every_seed*) check yes yes "bug reported as fails on every seed";; *) check no yes "bug reported as fails on every seed";; esac
case "$v" in *flaky*) check flaky none "no flaky verdicts on a deterministic bug";; esac
rm -rf "$tmp"

echo "== 3. demo faults"
rm -f "${TMPDIR:-/tmp}/fifo_triage_demo_marker"
python3 tools/triage.py --module test_triage_demo --seeds "$SEEDS" --out results/triage_selftest/demo >/dev/null; check $? 1 "demo exits 1"
v=$(verdicts results/triage_selftest/demo/triage_report.json); echo "  $v"
case "$v" in *test_demo_testbench_bug=fails_on_some_seeds*) check yes yes "testbench bug: fails on some seeds";; *) check no yes "testbench bug: fails on some seeds";; esac
case "$v" in *test_demo_leaky_state=flaky*) check yes yes "leaky state: flaky";; *) check no yes "leaky state: flaky";; esac
rm -f "${TMPDIR:-/tmp}/fifo_triage_demo_marker"

[ $fail = 0 ] && echo "triage self-test passed" || echo "triage self-test FAILED"
exit $fail
