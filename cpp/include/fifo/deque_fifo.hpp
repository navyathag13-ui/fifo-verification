// deque_fifo.hpp -- behavioral reference, the C++ twin of verif/ref_model.py.
//
// Deliberately written a different way from PointerFifo (a std::deque and
// a count, no pointers or wrap bits) so the two can check each other: a
// bug in the pointer arithmetic shows up as a disagreement instead of
// being copied into the reference.
#pragma once

#include <cstdint>
#include <deque>

#include "fifo/pointer_fifo.hpp"

namespace fifo {

class DequeFifo {
public:
    DequeFifo(unsigned depth, unsigned data_width)
        : depth_(depth), mask_(data_width == 32 ? 0xFFFFFFFFu : ((1u << data_width) - 1)) {}

    bool full() const { return data_.size() >= depth_; }
    bool empty() const { return data_.empty(); }
    std::uint32_t rd_data() const { return rd_data_; }
    std::size_t count() const { return data_.size(); }

    void reset() {
        data_.clear();
        rd_data_ = 0;
    }

    StepResult step(bool wr_en, std::uint32_t wr_data, bool rd_en) {
        const bool was_full = full();
        const bool was_empty = empty();
        StepResult r;
        if (rd_en && !was_empty) {  // pop first is safe: both use pre-edge flags
            rd_data_ = data_.front();
            data_.pop_front();
            r.popped = true;
            r.popped_value = rd_data_;
        }
        if (wr_en && !was_full) {
            data_.push_back(wr_data & mask_);
            r.pushed = true;
        }
        return r;
    }

private:
    unsigned depth_;
    std::uint32_t mask_;
    std::deque<std::uint32_t> data_;
    std::uint32_t rd_data_ = 0;
};

}  // namespace fifo
