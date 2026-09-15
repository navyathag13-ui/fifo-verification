// async_fifo.v -- Parameterized dual-clock (asynchronous) FIFO.
//
// Same external contract as sync_fifo.v, but wr_clk/wr_rst_n and
// rd_clk/rd_rst_n are independent, unrelated clock domains -- this is
// the standard Cummings-style design (Clifford E. Cummings, "Simulation
// and Synthesis Techniques for Asynchronous FIFO Design", SNUG 2002),
// the canonical reference for this exact structure.
//
// Why this is harder than sync_fifo.v: a binary pointer can have
// multiple bits change in the same transition (e.g. 0111 -> 1000, four
// bits flip at once). Synchronizing a multi-bit binary value across a
// clock domain gives no guarantee all bits land in the same cycle on
// the far side -- a partially-updated ("torn") value can be read as a
// completely different, wrong number. Gray code fixes this structurally:
// exactly one bit changes per increment, so a synchronizer sampling a
// Gray-coded pointer mid-transition reads either the old value or the
// new value, never a value that was never valid.
//
// IEEE 1364-2005 only (no SystemVerilog constructs) -- compiled with
// `-g2005` in the Makefile, same as sync_fifo.v.

module async_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16   // must be a power of 2
) (
    // Write domain
    input  wire                  wr_clk,
    input  wire                  wr_rst_n,   // active-low, synchronous to wr_clk
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    output reg                   full,

    // Read domain
    input  wire                  rd_clk,
    input  wire                  rd_rst_n,   // active-low, synchronous to rd_clk
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output reg                   empty
);

    localparam ADDR_WIDTH = $clog2(DEPTH);

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // All pointer/synchronizer registers declared up front: the write
    // domain's synchronizer references the read domain's rd_ptr_gray
    // (and vice versa), so under strict IEEE 1364-2005 elaboration
    // (-g2005) every signal must be declared before any use, regardless
    // of which "domain section" below it conceptually belongs to.
    reg [ADDR_WIDTH:0] wr_ptr_bin, wr_ptr_gray;
    reg [ADDR_WIDTH:0] rd_ptr_bin, rd_ptr_gray;
    reg [ADDR_WIDTH:0] rd_ptr_gray_sync1, rd_ptr_gray_sync2;
    reg [ADDR_WIDTH:0] wr_ptr_gray_sync1, wr_ptr_gray_sync2;

    // -----------------------------------------------------------------
    // Write domain: binary pointer (for memory addressing) + its Gray
    // -coded twin (the only thing that ever crosses into the read
    // domain).
    // -----------------------------------------------------------------
    wire [ADDR_WIDTH:0] wr_ptr_bin_next  = wr_ptr_bin + (wr_en && !full);
    wire [ADDR_WIDTH:0] wr_ptr_gray_next = (wr_ptr_bin_next >> 1) ^ wr_ptr_bin_next;

    always @(posedge wr_clk) begin
        if (!wr_rst_n) begin
            wr_ptr_bin  <= {(ADDR_WIDTH+1){1'b0}};
            wr_ptr_gray <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            wr_ptr_bin  <= wr_ptr_bin_next;
            wr_ptr_gray <= wr_ptr_gray_next;
            if (wr_en && !full)
                mem[wr_ptr_bin[ADDR_WIDTH-1:0]] <= wr_data;
        end
    end

    // 2-flop synchronizer bringing the read pointer's Gray code into
    // the write domain. Two stages, not one: the first flop is the one
    // that could theoretically go metastable catching an
    // asynchronously-changing input; the second flop gives it a full
    // clock period to resolve before anything downstream uses the
    // value. (Functional RTL simulation can't actually model that
    // metastable resolution -- see README's CDC section for exactly
    // what this testbench can and can't prove.)
    always @(posedge wr_clk) begin
        if (!wr_rst_n) begin
            rd_ptr_gray_sync1 <= {(ADDR_WIDTH+1){1'b0}};
            rd_ptr_gray_sync2 <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            rd_ptr_gray_sync1 <= rd_ptr_gray;
            rd_ptr_gray_sync2 <= rd_ptr_gray_sync1;
        end
    end

    // Full when the *next* write Gray pointer would equal the
    // synchronized read Gray pointer with its top two bits inverted --
    // the Gray-code equivalent of "write pointer has lapped read
    // pointer by exactly one full trip around the buffer." Registered
    // (not a bare combinational assign) so `full` never glitches
    // mid-comparison.
    wire full_next = (wr_ptr_gray_next ==
        {~rd_ptr_gray_sync2[ADDR_WIDTH:ADDR_WIDTH-1], rd_ptr_gray_sync2[ADDR_WIDTH-2:0]});

    always @(posedge wr_clk) begin
        if (!wr_rst_n)
            full <= 1'b0;
        else
            full <= full_next;
    end

    // -----------------------------------------------------------------
    // Read domain: mirror image of the write domain.
    // -----------------------------------------------------------------
    wire [ADDR_WIDTH:0] rd_ptr_bin_next  = rd_ptr_bin + (rd_en && !empty);
    wire [ADDR_WIDTH:0] rd_ptr_gray_next = (rd_ptr_bin_next >> 1) ^ rd_ptr_bin_next;

    always @(posedge rd_clk) begin
        if (!rd_rst_n) begin
            rd_ptr_bin  <= {(ADDR_WIDTH+1){1'b0}};
            rd_ptr_gray <= {(ADDR_WIDTH+1){1'b0}};
            rd_data     <= {DATA_WIDTH{1'b0}};
        end else begin
            rd_ptr_bin  <= rd_ptr_bin_next;
            rd_ptr_gray <= rd_ptr_gray_next;
            if (rd_en && !empty)
                rd_data <= mem[rd_ptr_bin[ADDR_WIDTH-1:0]];
        end
    end

    // 2-flop synchronizer bringing the write pointer's Gray code into
    // the read domain.
    always @(posedge rd_clk) begin
        if (!rd_rst_n) begin
            wr_ptr_gray_sync1 <= {(ADDR_WIDTH+1){1'b0}};
            wr_ptr_gray_sync2 <= {(ADDR_WIDTH+1){1'b0}};
        end else begin
            wr_ptr_gray_sync1 <= wr_ptr_gray;
            wr_ptr_gray_sync2 <= wr_ptr_gray_sync1;
        end
    end

    // Empty when the *next* read Gray pointer would equal the
    // synchronized write Gray pointer exactly -- no bit inversion
    // needed here, unlike full: pointers being Gray-equal always means
    // "caught up," whether that's because nothing was ever written or
    // because everything written has been read.
    wire empty_next = (rd_ptr_gray_next == wr_ptr_gray_sync2);

    always @(posedge rd_clk) begin
        if (!rd_rst_n)
            empty <= 1'b1;
        else
            empty <= empty_next;
    end

endmodule
