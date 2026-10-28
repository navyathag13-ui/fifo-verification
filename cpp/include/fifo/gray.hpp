// gray.hpp -- the Gray-code conversions rtl/async_fifo.v uses to carry
// pointers across clock domains. A Gray-coded pointer changes exactly one
// bit per increment, so a synchronizer can only ever sample the old value
// or the new one, never a torn mix of both.
#pragma once

#include <cstdint>

namespace fifo {

constexpr std::uint32_t to_gray(std::uint32_t binary) { return binary ^ (binary >> 1); }

constexpr std::uint32_t from_gray(std::uint32_t gray) {
    std::uint32_t binary = gray;
    for (std::uint32_t shift = 1; shift < 32; shift <<= 1) binary ^= binary >> shift;
    return binary;
}

}  // namespace fifo
