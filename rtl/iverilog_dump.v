// iverilog_dump.v -- Standalone VCD dump helper for Icarus Verilog.
//
// Not part of the design under test. Icarus elaborates every module with
// no instantiating parent as its own root, so this compiles alongside
// sync_fifo.v and dumps its signals without needing a wrapper testbench
// module around the DUT itself.

module iverilog_dump();
    initial begin
        $dumpfile("results/waves.vcd");
        $dumpvars(0, sync_fifo);
    end
endmodule
