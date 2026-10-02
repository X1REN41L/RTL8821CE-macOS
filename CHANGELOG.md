# Changelog

## 1.0.0 — 2026-10-02

First version under the independent RTL88WiFi name. Includes every fix from
our prior experimental builds through r11, with the complete maintained
source and five host validation suites.

- Rename the kext/executable to `RTL88WiFi`, the bundle ID to
  `io.github.x1ren41l.RTL88WiFi`, and the native controller/interface classes
  to `RTL88WiFi` / `RTL88WiFiInterface`.
- Restart versioning at 1.0.0; build identity
  `1.0.0-rtl88wifi-r11-20261002`.
- Include r10's 64-packet output pull limit, experimental outputStart gate,
  multicast/NoAck RX reorder bypass, and scan/beacon TIM and padding fixes.
- Include r11's TX-stall/BE-ring gate, resume and timer safety paths, and
  queue drop/stall counters. The r11 change is not yet hardware-tested.
- Retain all earlier WPA2/group-rekey, peer capability, memory, station,
  firmware, scan, disconnect-reason, RX security and diagnostic fixes.
- Update OpenCore paths and migration instructions; preserve licenses,
  credits and source provenance.

The r10 predecessor was hardware-tested on RTL8821CE / Sonoma 14.8.9.
The renamed 1.0.0 package needs a new hardware boot/load check. The measured
remaining heavy-load queue drops and unsupported features are documented in
README.md. This release does not claim upstream release numbering.
