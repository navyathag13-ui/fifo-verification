// Directed tests: one per real way a FIFO breaks, the same bug classes the
// cocotb suite targets in verif/test_sync_fifo.py.
#include <gtest/gtest.h>

#include <stdexcept>

#include "fifo/pointer_fifo.hpp"

using fifo::PointerFifo;

namespace {

void fill(PointerFifo& f, unsigned n, std::uint32_t start = 1) {
    for (unsigned i = 0; i < n; ++i) f.step(true, start + i, false);
}

}  // namespace

TEST(PointerFifo, StartsEmptyAndNotFull) {
    PointerFifo f(8, 8);
    EXPECT_TRUE(f.empty());
    EXPECT_FALSE(f.full());
}

TEST(PointerFifo, RejectsDepthThatIsNotAPowerOfTwo) {
    EXPECT_THROW(PointerFifo(12, 8), std::invalid_argument);
    EXPECT_THROW(PointerFifo(1, 8), std::invalid_argument);
}

TEST(PointerFifo, SingleWriteThenReadReturnsTheValue) {
    PointerFifo f(8, 8);
    f.step(true, 0x5A, false);
    const auto r = f.step(false, 0, true);
    ASSERT_TRUE(r.popped);
    EXPECT_EQ(*r.popped_value, 0x5Au);
    EXPECT_EQ(f.rd_data(), 0x5Au);
    EXPECT_TRUE(f.empty());
}

TEST(PointerFifo, FullExactlyAtDepthNotOneEarly) {
    PointerFifo f(8, 8);
    fill(f, 7);
    EXPECT_FALSE(f.full()) << "full one entry early wastes a slot";
    fill(f, 1, 100);
    EXPECT_TRUE(f.full());
}

TEST(PointerFifo, PushWhileFullIsDroppedAndOldestEntryIsIntact) {
    PointerFifo f(4, 8);
    fill(f, 4, 10);  // 10, 11, 12, 13
    const auto r = f.step(true, 99, false);
    EXPECT_FALSE(r.pushed);
    EXPECT_EQ(*f.step(false, 0, true).popped_value, 10u) << "overflow ate the oldest entry";
}

TEST(PointerFifo, PopWhileEmptyChangesNothing) {
    PointerFifo f(4, 8);
    const auto r = f.step(false, 0, true);
    EXPECT_FALSE(r.popped);
    f.step(true, 7, false);
    EXPECT_EQ(*f.step(false, 0, true).popped_value, 7u) << "an empty pop corrupted the read pointer";
}

TEST(PointerFifo, SimultaneousPushAndPopWhenEmptyOnlyPushes) {
    PointerFifo f(4, 8);
    const auto r = f.step(true, 3, true);
    EXPECT_TRUE(r.pushed);
    EXPECT_FALSE(r.popped) << "pop must use the pre-edge empty flag";
    EXPECT_FALSE(f.empty());
}

TEST(PointerFifo, SimultaneousPushAndPopWhenFullOnlyPops) {
    PointerFifo f(4, 8);
    fill(f, 4, 1);
    const auto r = f.step(true, 50, true);
    EXPECT_TRUE(r.popped);
    EXPECT_FALSE(r.pushed) << "push must use the pre-edge full flag";
    EXPECT_FALSE(f.full());
}

TEST(PointerFifo, ResetMidTrafficClearsBothPointers) {
    PointerFifo f(4, 8);
    fill(f, 3);
    f.step(false, 0, true);
    f.reset();
    EXPECT_TRUE(f.empty());
    EXPECT_FALSE(f.full());
    EXPECT_EQ(f.rd_data(), 0u);
    f.step(true, 42, false);
    EXPECT_EQ(*f.step(false, 0, true).popped_value, 42u) << "a stale pointer survived reset";
}

TEST(PointerFifo, BackToBackTrafficWrapsThePointersCorrectly) {
    PointerFifo f(4, 8);
    f.step(true, 0, false);
    for (std::uint32_t i = 1; i < 40; ++i) {  // wraps the 3-bit pointers several times
        const auto r = f.step(true, i, true);
        ASSERT_TRUE(r.popped);
        EXPECT_EQ(*r.popped_value, i - 1);
    }
}

TEST(PointerFifo, DataWiderThanTheConfiguredWidthIsMasked) {
    PointerFifo f(4, 8);
    f.step(true, 0x1FF, false);
    EXPECT_EQ(*f.step(false, 0, true).popped_value, 0xFFu);
}
