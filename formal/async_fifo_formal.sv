// async_fifo_formal.sv -- Formal properties for async_fifo.v.
//
// Same black-box-wrapper approach as sync_fifo_formal.sv: this checks
// the DUT purely through its own ports, never reaching into internals.
//
// First attempt at this file tried `multiclock on` with wr_clk and
// rd_clk left as fully independent free primary inputs, so the solver
// could pick any relative ordering of edges. That broke reset: with
// synchronous (not async) resets, a register only actually clears when
// its own clock ticks while rst_n is held low, and under multiclock
// unrolling the solver is free to just never toggle a given clock
// during the reset window, leaving that domain's registers at their
// arbitrary initial values forever. The counterexample it found wasn't
// a real bug -- it was the DUT never getting reset at all, confirmed by
// dumping the generated trace testbench and finding wr_push_count and
// rd_pop_count sitting at arbitrary nonzero values at step 0 with no
// clock edge having fired yet. Getting real fairness/toggling
// constraints on independently-free clocks correct is its own project;
// rather than bolt on unverified constraints to paper over it, this
// version ties wr_clk and rd_clk to the same underlying clock instead.
//
// That's a real, documented scope reduction: this proof does NOT
// explore arbitrary asynchronous relative-phase orderings between the
// two domains the way true CDC formal verification would. What it does
// check, exhaustively, is that the FIFO's control logic -- the
// Gray-code pointers, the 2-flop synchronizers, the full/empty
// comparisons -- is self-consistent and never overflows or reports
// full-and-empty simultaneously, when both domains are clocked in
// lockstep. That's strictly less than the real deployment scenario, but
// it still exercises every line of the synchronizer and comparison
// logic and would catch the same class of control-logic bug the
// bug-injection test below catches. See the README's CDC section for
// what the cocotb testbench separately covers and what neither tool
// claims to prove about true clock-domain-independent metastability.
//
// First draft of the shadow-tracking logic used a single shadow_count
// register updated from two separate always blocks (one per clock
// domain) -- a multi-driver register, which is simply invalid and
// should never have been written that way. Fixed by splitting it into
// two free-running, single-driver counters: wr_push_count counts every
// accepted write, rd_pop_count counts every accepted read, each driven
// by exactly one always block. The live occupancy is their plain
// difference, read combinationally wherever needed.

module async_fifo_formal_top #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16
) (
    input  wire                  clk,
    input  wire                  wr_rst_n,
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    input  wire                  rd_rst_n,
    input  wire                  rd_en
);
    localparam ADDR_WIDTH = $clog2(DEPTH);

    wire [DATA_WIDTH-1:0] rd_data;
    wire                  full;
    wire                  empty;

    async_fifo #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(DEPTH)
    ) dut (
        .wr_clk(clk), .wr_rst_n(wr_rst_n), .wr_en(wr_en), .wr_data(wr_data), .full(full),
        .rd_clk(clk), .rd_rst_n(rd_rst_n), .rd_en(rd_en), .rd_data(rd_data), .empty(empty)
    );

    // Forces every explored trace to genuinely start in reset -- same
    // reasoning as the sync harness's `initial assume`.
    initial assume (!wr_rst_n);
    initial assume (!rd_rst_n);

    // Both reset inputs move together for the rest of the trace too.
    // Without this, BMC finds "counterexamples" where one domain gets
    // reset mid-operation while the other keeps running with live data
    // still in flight -- a real, physically-meaningful scenario, but
    // one whose correct behavior isn't "FIFO stays consistent," it's
    // "the design doesn't promise anything meaningful here," so it's
    // out of scope for what this proof claims. A shared/synchronized
    // reset is the common real-world case anyway.
    always @(*) begin
        assume (wr_rst_n == rd_rst_n);
    end

    // Free-running, single-driver-per-domain counters. Each only ever
    // increments, driven by exactly one always block, so there's no
    // multi-driver hazard.
    reg [ADDR_WIDTH:0] wr_push_count;
    reg [ADDR_WIDTH:0] rd_pop_count;

    wire [ADDR_WIDTH:0] shadow_count = wr_push_count - rd_pop_count;

    always @(posedge clk) begin
        if (!wr_rst_n) begin
            wr_push_count <= {(ADDR_WIDTH+1){1'b0}};
        end else if (wr_en && !full) begin
            wr_push_count <= wr_push_count + 1'b1;
        end
    end

    always @(posedge clk) begin
        if (!rd_rst_n) begin
            rd_pop_count <= {(ADDR_WIDTH+1){1'b0}};
        end else if (rd_en && !empty) begin
            rd_pop_count <= rd_pop_count + 1'b1;
        end
    end

    always @(posedge clk) begin
        if (wr_rst_n && rd_rst_n) begin
            assert (!(full && empty));
            assert (shadow_count <= DEPTH);
        end
    end

endmodule
