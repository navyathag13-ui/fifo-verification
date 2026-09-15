// iverilog_dump_async.v -- VCD dump helper for the async_fifo testbench.
// See iverilog_dump.v for why this is a separate co-elaborated root
// rather than logic inside the design itself.

module iverilog_dump_async();
    initial begin
        $dumpfile("results/waves_async.vcd");
        $dumpvars(0, async_fifo);
    end
endmodule
