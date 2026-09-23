# Makefile -- cocotb build/simulation orchestration for the FIFO
# verification suites.
#
# Icarus Verilog is the primary simulator. -g2005 forces strict IEEE
# 1364-2005 compilation, so a SystemVerilog construct sneaking into the
# RTL fails the build instead of silently being accepted.
#
# `make`        -> sync FIFO suite (default)
# `make async`  -> async (dual-clock) FIFO suite
# `make DEPTH=8 DATA_WIDTH=16`  -> override the design parameters (DEPTH must be a power of 2)
# `make sweep`  -> run both suites across several depths and data widths

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

# Optional parameter overrides. The tests read DEPTH/DATA_WIDTH from the design itself,
# so the same suite runs unchanged at any size.
DEPTH ?=
DATA_WIDTH ?=
ifneq ($(DEPTH),)
COMPILE_ARGS += -P$(TOPLEVEL).DEPTH=$(DEPTH)
endif
ifneq ($(DATA_WIDTH),)
COMPILE_ARGS += -P$(TOPLEVEL).DATA_WIDTH=$(DATA_WIDTH)
endif
# cocotb's own -s $(TOPLEVEL) restricts elaboration to that one root;
# the dump helper has no instantiating parent either, so it needs its
# own explicit root or it's silently never elaborated (and never dumps).
COMPILE_ARGS += -s $(DUMP_MODULE)

# One build folder per configuration, so switching target or parameters never reuses a stale build.
CONFIG_TAG := $(SIM_TARGET)_d$(if $(DEPTH),$(DEPTH),default)_w$(if $(DATA_WIDTH),$(DATA_WIDTH),default)
SIM_BUILD := $(PROJECT_ROOT)/results/sim_build_$(CONFIG_TAG)
COCOTB_RESULTS_FILE := $(PROJECT_ROOT)/results/results_$(CONFIG_TAG).xml
export COVERAGE_XML := $(PROJECT_ROOT)/results/coverage.xml
export COVERAGE_ASYNC_XML := $(PROJECT_ROOT)/results/coverage_async.xml

include $(shell cocotb-config --makefiles)/Makefile.sim

.PHONY: clean-all async sweep

# `sim` is cocotb's own target (built by the include above); this project
# doesn't rename it, but `make` with no target already runs it.

async:
	$(MAKE) SIM_TARGET=async sim

sweep:
	@for d in 4 8 16 32; do for w in 8 16; do \
	  echo "== sync  DEPTH=$$d DATA_WIDTH=$$w"; $(MAKE) SIM_TARGET=sync DEPTH=$$d DATA_WIDTH=$$w sim || exit 1; \
	  echo "== async DEPTH=$$d DATA_WIDTH=$$w"; $(MAKE) SIM_TARGET=async DEPTH=$$d DATA_WIDTH=$$w sim || exit 1; \
	done; done

clean-all: clean
	rm -rf $(PROJECT_ROOT)/results/sim_build*
	rm -f $(PROJECT_ROOT)/results/results_*.xml $(PROJECT_ROOT)/results/coverage*.xml $(PROJECT_ROOT)/results/*.vcd
