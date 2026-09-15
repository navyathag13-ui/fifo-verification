// sync_fifo.v -- Parameterized synchronous FIFO.
//
// Pointer-based implementation: write and read pointers are each
// ADDR_WIDTH+1 bits wide. The extra (MSB) bit never participates in the
// memory address -- it only exists to disambiguate "full" from "empty"
// when the lower ADDR_WIDTH bits of both pointers are equal, which
// happens in both cases for a plain ADDR_WIDTH-bit pointer. This is the
// standard approach (vs. a fill-count counter) because it needs no extra
// adder/comparator beyond the pointer increments themselves, and the
// full/empty conditions fall out of simple XOR/equality checks on the
// pointers directly.
//
// IEEE 1364-2005 only (no SystemVerilog constructs) -- compiled with
// `-g2005` in the Makefile to enforce this at build time, not just by
// convention.

module sync_fifo #(
    parameter DATA_WIDTH = 8,
    parameter DEPTH      = 16   // must be a power of 2
) (
    input  wire                  clk,
    input  wire                  rst_n,     // active-low, synchronous
    input  wire                  wr_en,
    input  wire [DATA_WIDTH-1:0] wr_data,
    input  wire                  rd_en,
    output reg  [DATA_WIDTH-1:0] rd_data,
    output wire                  full,
    output wire                  empty
);

    localparam ADDR_WIDTH = $clog2(DEPTH);

    reg [DATA_WIDTH-1:0] mem [0:DEPTH-1];

    // Pointers carry one extra bit beyond the memory address width.
    reg [ADDR_WIDTH:0] wr_ptr;
    reg [ADDR_WIDTH:0] rd_ptr;

    wire [ADDR_WIDTH-1:0] wr_addr;
    wire [ADDR_WIDTH-1:0] rd_addr;

    assign wr_addr = wr_ptr[ADDR_WIDTH-1:0];
    assign rd_addr = rd_ptr[ADDR_WIDTH-1:0];

    // empty: pointers fully match (both address bits and the wrap bit).
    // full: address bits match but the wrap bit differs -- the write
    // pointer has lapped the read pointer exactly once.
    assign empty = (wr_ptr == rd_ptr);
    assign full  = (wr_addr == rd_addr) && (wr_ptr[ADDR_WIDTH] != rd_ptr[ADDR_WIDTH]);

    always @(posedge clk) begin
        if (!rst_n) begin
            wr_ptr <= {(ADDR_WIDTH+1){1'b0}};
        end else if (wr_en && !full) begin
            mem[wr_addr] <= wr_data;
            wr_ptr        <= wr_ptr + 1'b1;
        end
    end

    always @(posedge clk) begin
        if (!rst_n) begin
            rd_ptr  <= {(ADDR_WIDTH+1){1'b0}};
            rd_data <= {DATA_WIDTH{1'b0}};
        end else if (rd_en && !empty) begin
            rd_data <= mem[rd_addr];
            rd_ptr  <= rd_ptr + 1'b1;
        end
    end

endmodule
