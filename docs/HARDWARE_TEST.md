# First test on a real printer (read-only)

Run these with the printer idle (not printing, cleaning or flushing). None of them writes anything.

```
run_windows.bat discover
run_windows.bat info
run_windows.bat counters
run_windows.bat backup --full
```

(`./run_macos.command ...` on a Mac.)

`info` should show the model as detected from the device id, the ink levels and both waste counters as a percentage.
`backup --full` saves the whole EEPROM to the backup folder; keep that file, it is your safety net.

If all four succeed, the reset can be tried with `--dry-run` first:

```
run_windows.bat reset-waste --i-replaced-the-pads --dry-run
```

Please report the output of `info` (serial number can be masked) so the model can be marked as verified.
