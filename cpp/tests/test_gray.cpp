// Gray-code properties the async FIFO depends on.
#include <gtest/gtest.h>

#include <bitset>

#include "fifo/gray.hpp"

using fifo::from_gray;
using fifo::to_gray;

TEST(Gray, RoundTripsEveryValueUpTo16Bits) {
    for (std::uint32_t v = 0; v < (1u << 16); ++v) {
        ASSERT_EQ(from_gray(to_gray(v)), v) << v;
    }
}

TEST(Gray, NeighboursDifferInExactlyOneBitIncludingTheWrap) {
    // A pointer of N address bits plus a wrap bit counts 0 .. 2^(N+1)-1 and
    // then wraps to 0; every one of those steps must flip a single bit.
    for (unsigned bits = 2; bits <= 7; ++bits) {
        const std::uint32_t modulus = 1u << bits;
        for (std::uint32_t v = 0; v < modulus; ++v) {
            const std::uint32_t next = (v + 1) % modulus;
            const auto changed = std::bitset<32>(to_gray(v) ^ to_gray(next)).count();
            ASSERT_EQ(changed, 1u) << "bits=" << bits << " step " << v << "->" << next;
        }
    }
}

TEST(Gray, KnownValues) {
    EXPECT_EQ(to_gray(0b0000), 0b0000u);
    EXPECT_EQ(to_gray(0b0001), 0b0001u);
    EXPECT_EQ(to_gray(0b0010), 0b0011u);
    EXPECT_EQ(to_gray(0b0111), 0b0100u);
    EXPECT_EQ(to_gray(0b1000), 0b1100u);
}
