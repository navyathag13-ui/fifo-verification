// sync_fifo_formal.sv -- Formal properties for sync_fifo.v.
//
// Kept completely separate from the design (rtl/sync_fifo.v has to stay
// strict IEEE 1364-2005 for the simulation flow): this module
// instantiates the real DUT as a black box and checks it purely against
// its own inputs/outputs, never reaching into its internals.
//
// That's a deliberate choice, not just a style preference. The first
// version of this file tried to check the DUT's internal wr_ptr/rd_ptr
// registers directly via a hierarchical dot-path (dut.wr_ptr) from a
// wrapper module. It silently produced a formal check with zero
// $assert cells in the actual proved design -- `prep`'s flattening
// passes restructure the hierarchy in a way that broke the textual
// dot-path reference, and the buggy build of sync_fifo.v used to
// validate this (the same missing-wrap-bit bug the random test catches)
// passed the formal proof too, vacuously, because nothing was actually
// being checked. Caught by explicitly counting $assert cells after
// `prep` (`select -count */t:$assert`) and getting 0 back, not by the
// proof failing the way it should have.
//
// The shadow counter below is the fix: it tracks the live item count
// using only what a black-box view of the DUT can see -- wr_en/rd_en
// (which this harness itself drives) and full/empty (the DUT's own
// outputs) -- the same "don't trust internal signal names to stay
// stable" reasoning ref_model.py uses on the simulation side, just
// written as synthesizable Verilog instead of Python.
//
// What's being proved: the two invariants a pointer-based full/empty
// scheme is supposed to guarantee by construction, checked exhaustively
// rather than probabilistically:
//   1. full and empty are never simultaneously true
//   2. the live item count never exceeds DEPTH
// Random testing (test_fill_to_full, test_random_traffic, ...) makes
// these look true across whatever sequences happened to get generated.
// BMC proves them true for every reachable state up to the given depth.

module sync_fifo_formal_top #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16
) (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    input  wire                  rd_en
);
    localparam ADDR_WIDTH = $clog2(DEPTH);

    wire [DATA_WIDTH-1:0] rd_data;
    wire                  full;
    wire                  empty;

    sync_fifo #(
        .DATA_WIDTH(DATA_WIDTH),
        .DEPTH(DEPTH)
    ) dut (
        .clk(clk),
        .rst_n(rst_n),
        .wr_en(wr_en),
        .wr_data(wr_data),
        .rd_en(rd_en),
        .rd_data(rd_data),
        .full(full),
        .empty(empty)
    );

    // BMC explores arbitrary initial register states by default -- it
    // will happily start the trace with wr_ptr, rd_ptr, and
    // shadow_count already mutually inconsistent, then "fail" a
    // property that was never violated by any real sequence of events,
    // just by an initial state a real reset would never produce. This
    // forces every trace to genuinely start in reset, the same
    // precondition every real use of this FIFO has.
    initial assume (!rst_n);

    reg [ADDR_WIDTH:0] shadow_count;
    wire push_happens = wr_en && !full;
    wire pop_happens  = rd_en && !empty;

    always @(posedge clk) begin
        if (!rst_n) begin
            shadow_count <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            case ({push_happens, pop_happens})
                2'b10:   shadow_count <= shadow_count + 1'b1;
                2'b01:   shadow_count <= shadow_count - 1'b1;
                default: shadow_count <= shadow_count;  // both or neither: no net change
            endcase
        end
    end

    always @(posedge clk) begin
        if (rst_n) begin
            assert (!(full && empty));
            assert (shadow_count <= DEPTH);
            assert (full  == (shadow_count == DEPTH));
            assert (empty == (shadow_count == 0));
        end
    end

endmodule
