# Makefile -- cocotb build/simulation orchestration for the FIFO
# verification suites.
#
# Icarus Verilog is the primary simulator. -g2005 forces strict IEEE
# 1364-2005 compilation, so a SystemVerilog construct sneaking into the
# RTL fails the build instead of silently being accepted.
#
# `make`        -> sync FIFO suite (default)
# `make async`  -> async (dual-clock) FIFO suite

SIM ?= icarus
TOPLEVEL_LANG ?= verilog
SIM_TARGET ?= sync

PROJECT_ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))

ifeq ($(SIM_TARGET),async)
VERILOG_SOURCES = $(PROJECT_ROOT)/rtl/async_fifo.v $(PROJECT_ROOT)/rtl/iverilog_dump_async.v
TOPLEVEL = async_fifo
MODULE = test_async_fifo
DUMP_MODULE := iverilog_dump_async
else
VERILOG_SOURCES = $(PROJECT_ROOT)/rtl/sync_fifo.v $(PROJECT_ROOT)/rtl/iverilog_dump.v
TOPLEVEL = sync_fifo
MODULE = test_sync_fifo
DUMP_MODULE := iverilog_dump
endif

export PYTHONPATH := $(PROJECT_ROOT)/verif:$(PYTHONPATH)

COMPILE_ARGS += -g2005
# cocotb's own -s $(TOPLEVEL) restricts elaboration to that one root;
# the dump helper has no instantiating parent either, so it needs its
# own explicit root or it's silently never elaborated (and never dumps).
COMPILE_ARGS += -s $(DUMP_MODULE)

SIM_BUILD := $(PROJECT_ROOT)/results/sim_build
COCOTB_RESULTS_FILE := $(PROJECT_ROOT)/results/results_$(SIM_TARGET).xml
export COVERAGE_XML := $(PROJECT_ROOT)/results/coverage.xml
export COVERAGE_ASYNC_XML := $(PROJECT_ROOT)/results/coverage_async.xml

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: clean-all async

# `sim` is cocotb's own target (built by the include above); this project
# doesn't rename it, but `make` with no target already runs it.

async:
	$(MAKE) SIM_TARGET=async sim

clean-all: clean
	rm -rf $(PROJECT_ROOT)/results/sim_build
	rm -f $(PROJECT_ROOT)/results/results_*.xml $(PROJECT_ROOT)/results/coverage*.xml $(PROJECT_ROOT)/results/*.vcd
