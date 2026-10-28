// Randomized cross-check: PointerFifo against DequeFifo every cycle, for
// 5,000 cycles, across 4 depths x 2 widths x 10 seeds (80 runs).
//
// Traffic runs in phases (balanced, fill-heavy, drain-heavy, both-heavy)
// with bursty resets, the same shaping that fixed the flaky cocotb test:
// a flat 50/50 mix rarely sits at full, so it would rarely test full.
// Each run also checks it actually reached full, empty and a
// simultaneous push+pop, so a pass can't come from never visiting them.
#include <gtest/gtest.h>

#include <random>
#include <string>
#include <tuple>

#include "fifo/deque_fifo.hpp"
#include "fifo/pointer_fifo.hpp"

namespace {

struct Phase {
    double push;
    double pop;
};
constexpr Phase kPhases[] = {{0.5, 0.5}, {0.85, 0.2}, {0.2, 0.85}, {0.9, 0.9}};
constexpr int kCycles = 5000;
constexpr int kPhaseLength = 250;

class RandomVsReference : public ::testing::TestWithParam<std::tuple<unsigned, unsigned, unsigned>> {};

TEST_P(RandomVsReference, MatchesReferenceEveryCycle) {
    const auto [depth, width, seed] = GetParam();
    fifo::PointerFifo dut(depth, width);
    fifo::DequeFifo ref(depth, width);
    std::mt19937 rng(seed);
    std::uniform_real_distribution<double> coin(0.0, 1.0);
    std::uniform_int_distribution<std::uint32_t> value(0, 0xFFFFFFFFu);

    bool saw_full = false, saw_empty_after_data = false, saw_both = false;
    int reset_burst = 0;
    for (int cycle = 0; cycle < kCycles; ++cycle) {
        const Phase& ph = kPhases[(cycle / kPhaseLength) % 4];
        if (reset_burst == 0 && coin(rng) < 0.005) reset_burst = 1 + static_cast<int>(rng() % 3);
        if (reset_burst > 0) {
            dut.reset();
            ref.reset();
            --reset_burst;
            continue;
        }
        const bool wr = coin(rng) < ph.push;
        const bool rd = coin(rng) < ph.pop;
        const std::uint32_t data = value(rng);
        const auto got = dut.step(wr, data, rd);
        const auto want = ref.step(wr, data, rd);

        ASSERT_EQ(got.pushed, want.pushed) << "cycle " << cycle;
        ASSERT_EQ(got.popped, want.popped) << "cycle " << cycle;
        ASSERT_EQ(got.popped_value, want.popped_value) << "cycle " << cycle;
        ASSERT_EQ(dut.full(), ref.full()) << "cycle " << cycle;
        ASSERT_EQ(dut.empty(), ref.empty()) << "cycle " << cycle;
        ASSERT_EQ(dut.rd_data(), ref.rd_data()) << "cycle " << cycle;

        saw_full |= ref.full();
        saw_empty_after_data |= (got.popped && ref.empty());
        saw_both |= (got.pushed && got.popped);
    }
    EXPECT_TRUE(saw_full) << "traffic never filled the FIFO";
    EXPECT_TRUE(saw_empty_after_data) << "traffic never drained the FIFO";
    EXPECT_TRUE(saw_both) << "traffic never pushed and popped on the same cycle";
}

INSTANTIATE_TEST_SUITE_P(DepthsWidthsSeeds, RandomVsReference,
                         ::testing::Combine(::testing::Values(4u, 8u, 16u, 32u),
                                            ::testing::Values(8u, 16u),
                                            ::testing::Range(0u, 10u)),
                         [](const auto& info) {
                             return "d" + std::to_string(std::get<0>(info.param)) + "_w" +
                                    std::to_string(std::get<1>(info.param)) + "_seed" +
                                    std::to_string(std::get<2>(info.param));
                         });

}  // namespace
