# Firmware input

Use the original **Z8 C3.11 MAIN payload** loaded at `0x40160000`:

- Size: **81,807,709 bytes**.
- SHA-256: `2b43a31c9de838f84b12416de4348a7004e65be07f853ec56ec2b10f3a8e3853`.
- The packaged component’s trailing CRC bytes `20 1b` are excluded.

Both launchers enforce this identity. Supply a compatible payload locally;
firmware is not included or downloaded by these tools.

`tools/rom_inputs.py` creates small synthetic external-ROM fixtures in the
run directory. Capture also requires the experimental bank-8 input at
`0x45a403e7` and processing-selector input at `0x47f5af45`, both set to 1.
These are explicit hypotheses, not recovered factory calibration or parameter
tables. Guest instruction bytes are preserved.

Place firmware and runtime artifacts outside the repository or under ignored
`.local/`.
