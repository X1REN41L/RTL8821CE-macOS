# Changelog

## 1.0.0 — 2026-10-02

First release under the RTL88WiFi name.

- Driver, executable and bundle renamed to `RTL88WiFi`
  (`io.github.x1ren41l.RTL88WiFi`), with native controller/interface classes
  `RTL88WiFi` / `RTL88WiFiInterface`. Build identity
  `1.0.0-rtl88wifi-r11-20261002`.
- WPA2 handshake retries, key installation and group rekeys fixed; stable
  SNonce; idempotent key install.
- Router HT/VHT capabilities parsed and used (5 GHz at line rate).
- Memory, firmware-bounds and station-lifetime fixes.
- Correct disconnect reasons, Sonoma-format network info, SSIDs kept in scan
  results, AP IE list ABI fix.
- Beacon TIM kept for the connected network and scan padding no longer
  copied (hidden-network label after wakes and network switches).
- Undecrypted/plaintext frames on protected links dropped; FragAttacks
  A-MSDU check; multicast and NoAck QoS traffic bypass RX reordering.
- Output-pull limit and two experimental output gates. On the current
  IO80211 push data path these gates do not engage; they are kept for
  diagnostics.
- Built-in `DiagnosticLog` with queue drop/stall counters.
- Added `tools/rtl88wifi-check.sh`, `docs/COMPATIBILITY.md` and issue
  templates for compatibility reports.

Hardware verification (RTL8821CE, Sonoma 14.8.9): load and join, ~15 minutes
of load and idle without link drops, 0% idle ping loss, `networkQuality`
86–87 down / 89–105 up Mbps. Known remaining issue: queue drops under heavy
parallel uploads (see README).
