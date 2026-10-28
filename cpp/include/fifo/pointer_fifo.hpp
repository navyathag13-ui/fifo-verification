// pointer_fifo.hpp -- cycle-accurate C++ model of rtl/sync_fifo.v.
//
// Mirrors the RTL's design choices rather than just its behavior:
// read and write pointers carry one extra wrap bit beyond the address
// width, empty is "pointers equal", full is "addresses equal, wrap bits
// differ", and push and pop on the same cycle are both decided against
// the full/empty state from *before* the clock edge (the RTL's two
// always blocks don't see each other's update). rd_data is a register:
// it only changes on a successful pop and holds otherwise.
//
// FIFO_PLANTED_BUG (CMake option) swaps in known-bad logic so the test
// suite can be shown to fail when the model is wrong.
#pragma once

#include <cstdint>
#include <optional>
#include <stdexcept>
#include <vector>

namespace fifo {

struct StepResult {
    bool pushed = false;
    bool popped = false;
    std::optional<std::uint32_t> popped_value;
};

class PointerFifo {
public:
    PointerFifo(unsigned depth, unsigned data_width)
        : depth_(depth), mask_(width_mask(data_width)), mem_(depth, 0) {
        if (depth < 2 || (depth & (depth - 1)) != 0) {
            throw std::invalid_argument("depth must be a power of two, at least 2");
        }
        addr_bits_ = 0;
        while ((1u << addr_bits_) < depth) ++addr_bits_;
        ptr_mask_ = (1u << (addr_bits_ + 1)) - 1;  // address bits plus the wrap bit
    }

    bool empty() const { return wr_ptr_ == rd_ptr_; }

    bool full() const {
#if defined(FIFO_PLANTED_BUG_WRAP_BIT)
        return addr(wr_ptr_) == addr(rd_ptr_);  // ignores the wrap bit: full whenever empty
#else
        return addr(wr_ptr_) == addr(rd_ptr_) && wrap(wr_ptr_) != wrap(rd_ptr_);
#endif
    }

    std::uint32_t rd_data() const { return rd_data_; }
    unsigned depth() const { return depth_; }

    void reset() {
        wr_ptr_ = 0;
#if !defined(FIFO_PLANTED_BUG_PARTIAL_RESET)
        rd_ptr_ = 0;  // the planted bug leaves the read pointer stale
#endif
        rd_data_ = 0;
    }

    StepResult step(bool wr_en, std::uint32_t wr_data, bool rd_en) {
        const bool was_full = full();    // both decisions use the pre-edge state
        const bool was_empty = empty();
        StepResult r;
        if (wr_en && !was_full) {
            mem_[addr(wr_ptr_)] = wr_data & mask_;
            wr_ptr_ = (wr_ptr_ + 1) & ptr_mask_;
            r.pushed = true;
        }
        if (rd_en && !was_empty) {
            rd_data_ = mem_[addr(rd_ptr_)];
            rd_ptr_ = (rd_ptr_ + 1) & ptr_mask_;
            r.popped = true;
            r.popped_value = rd_data_;
        }
        return r;
    }

private:
    static std::uint32_t width_mask(unsigned bits) {
        if (bits == 0 || bits > 32) throw std::invalid_argument("data_width must be 1..32");
        return bits == 32 ? 0xFFFFFFFFu : ((1u << bits) - 1);
    }
    unsigned addr(unsigned ptr) const { return ptr & (depth_ - 1); }
    unsigned wrap(unsigned ptr) const { return (ptr >> addr_bits_) & 1u; }

    unsigned depth_;
    std::uint32_t mask_;
    std::vector<std::uint32_t> mem_;
    unsigned addr_bits_ = 0;
    unsigned ptr_mask_ = 0;
    unsigned wr_ptr_ = 0;
    unsigned rd_ptr_ = 0;
    std::uint32_t rd_data_ = 0;
};

}  // namespace fifo
