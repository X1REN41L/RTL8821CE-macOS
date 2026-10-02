# Host validation

These five suites exercise the actual driver functions with host substitutes
for kernel/hardware services, using ASan/UBSan. They cover firmware bounds,
HT/VHT peer capabilities, station lifetime, diagnostic buffers, WPA2
handshake/GTK rekeys, protected RX and A-MSDU filtering, and scan SSID/TIM
handling. Timer lifecycle checks inspect source ordering rather than execute
IOKit. They do not establish kernel load or hardware behavior.

Run from the repository root on macOS with Xcode Command Line Tools:

```sh
python3 tests/test-focused.py
python3 tests/test-group-key.py
python3 tests/test-handshake.py
python3 tests/test-rx-filter.py
python3 tests/test-scan-ssid.py
```

Build the complete driver with `make -C driver/RTL88WiFi rtl88wifi`.
