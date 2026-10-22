# Read-only execution tracing

`z8trace` adapts the Z63 call-observation and memory-watch mechanisms to the
QEMU 11 plugin API. It uses explicit caller-supplied instruction addresses and
memory/code intervals. No Z63 firmware logging hooks, register writes, stack
scan, automatic address relocation or camera-command interface is included.

Build against the same QEMU source used by the emulator:

```sh
python3 plugins/build.py --qemu-source /path/to/qemu-11.1.1 \
  --output .local/plugins/libz8trace.dylib
```

Use `.so` for Linux. The compiler and GLib development headers are required;
QEMU must have plugin support enabled. The plugin requires API version 7.
Compiled plugins are external inputs, never bundled with the desktop app.
Use a binary built from the reviewed plugin source: the launcher records its
hash, but a supplied filename alone does not verify an external binary's behavior.

Add these optional fields to an existing desktop configuration:

```json
{
  "trace_plugin": "/absolute/path/to/libz8trace.dylib",
  "trace_calls": [1075183616],
  "trace_cpu": 0,
  "trace_limit": 10000,
  "trace_per_site": 4
}
```

The sample address is `0x40160000`, the existing MAIN boot entry; observing an
instruction does not prove it is a function call. Addresses are exact executed
instruction sites, even for Thumb; remove a pointer's Thumb tag explicitly.
Omit `trace_cpu` to observe all supported vCPUs. Use **Session → Show diagnostics
→ Plugin trace** to inspect the output. The picker is disabled when tracing is
not configured. Restart creates a new trace in the new session folder; Stop
flushes its summary and retains the log. Input-file access checks cover the
configured plugin just like other explicit local inputs.

The equivalent CLI options work in `tools/run.py` and `tools/run_native.py`:

```sh
--trace-plugin /absolute/path/to/libz8trace.dylib \
--trace-call 0x40160000 --trace-cpu 0 --trace-limit 10000 --trace-per-site 4
```

For store observation, supply `--trace-watch LO:HI:PCLO:PCHI`, or desktop
`trace_watch` with exactly the numeric fields `lo`, `hi`, `pclo`, `pchi`.
Intervals are increasing and end-exclusive; both the code interval and memory
interval are required. Stores overlapping the watched memory interval count;
stores from outside the code interval do not. Calls and watches can coexist.
No ranges or instruction sites are inferred from another camera/version.

The private `plugin-trace.log` is JSON Lines: a start record, call/store/application records
and an exit summary. Call records contain vCPU, PC, four argument-register
values and the link register; unavailable registers are `null`. QEMU 11 register
zero can have a null-valued opaque handle, so descriptor presence is tracked
separately. Store records contain the actual address, access size and value,
including the API's 128-bit value form. `host_us` measures elapsed host monotonic
time, not virtual camera time, cycle accuracy or measured hardware latency.

Defaults are four records per distinct `(CPU, kind, PC, address)`, 10,000 total
records and at most 4,096 retained sites. Limits are bounded to 1..1,000,000.
Unknown/duplicate options, odd/duplicate call addresses, incomplete ranges and
existing output paths are rejected. Output is created exclusively with mode
0600; trace values remain local and require review before sharing. Tracing can
slow emulation and is disabled by default. Check-only validates the profile and
paths; it does not load or qualify a plugin binary.

Run the firmware-free real-plugin checks with:

```sh
python3 tests/check_trace_plugin.py --qemu /path/to/qemu-system-aarch64 \
  --plugin .local/plugins/libz8trace.dylib --output .local/new-trace-check
```

All 84 checks pass on the built macOS QEMU: real synthetic A53/M4 calls and
stores, exact argument/data values, per-site/total bounds, CPU/address/code
filtering, overlapping stores, rejected configurations and no-replace output.
Application-entry controls additionally check the fifth register, low32 truncation, untouched null/unaligned/unmapped object addresses, explicit unsupported M4 hits and coexistence with calls/stores. Both guest programs continue independently. These checks qualify the plugin
API/model integration; format-aware firmware logging, interactive console,
USB and physical-camera behavior remain separate.

Native macOS checks also confirm the configured trace in Diagnostics, a fresh
trace after restart, retained output after Stop and a disabled picker when the
profile omits tracing. Those checks do not qualify Linux/Windows desktop bundles.


## Numeric application-ring entries

`--trace-app-log ADDRESS` (desktop `trace_app_log`, a numeric address) selects
one independently identified AArch64 application-ring writer entry. The address
must be nonzero and aligned to four bytes. This optional schema reads X0 as an
opaque object address, W1 as a stream selector and W2/W3/W4 as three unsigned
32-bit payload values. It also retains the link register. Selector values are
numeric; no severity or module names are assigned.

The observer never dereferences the object or reads guest memory. In particular,
`module_id` is always `null` with `module_id_source: "not_read"`; an invalid
object cannot trigger an MMIO read. Unavailable registers remain null. A hit on
a non-AArch64 CPU reports `abi_available: false` and null ABI values. The
existing generic call schema still reports four argument registers.

Application entries share CPU filtering, output/site limits and no-replace log
creation with calls/stores. They can be selected alone or alongside either.
The configured entry must implement this ABI for its exact firmware version;
no hook address is shipped. An observed entry does not establish admission,
a completed ring write, decoded format strings or a physical-camera event.
Full stock log formatting, TOPPERS and EX log decoding remain open.


A separate original Z8 MAIN/EX run with an independently recovered entry records
34 application events on MAIN CPUs 0/1/2, with numeric register values and module
IDs explicitly unavailable. Caps suppress further hits; transport has no checksum
failures and owned shutdown is clean. The run ends at a separate strict playback
boundary. This qualifies entry observation, without promoting it to a completed
ring write, formatted logging or a complete playback workflow.
