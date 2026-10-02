# Source origin and notices

RTL88WiFi 1.0.0 is an independently maintained derivative by X1REN41L.
It is based on AirPort_RTW88 by xnoah222, distributed through
https://github.com/xnoah222/Realtek-AirPort-Family. It has its own name,
bundle identifier (`io.github.x1ren41l.RTL88WiFi`), source tree and version
sequence. It is not an official continuation of AirPort_RTW88.

## Source snapshot

The starting source was `AirPort_RTW88-Source.zip` from Realtek-AirPort-Family
commit `1885e37304bdc589755c94190c5b20bed1244669`.
Archive SHA-256:
`0c896c64270e0de3fa84c5d825b7b9d391bf6867effb3f2fc56922bd3e2cdf1c`.
The original source archive and research snapshots remain preserved in the
development workspace. This repository includes the corresponding maintained
source in `driver/RTL88WiFi` and `driver/rtw88-stable`.

## Changes made here

Between 2026-09-30 and 2026-10-02, X1REN41L's experimental build added memory,
station-lifetime and firmware bounds fixes; WPA2 handshake/key-install and
group-rekey corrections; HT/VHT peer capabilities; Sonoma scan and AP-IE
compatibility; disconnect reasons; protected-frame and A-MSDU filtering;
diagnostics; r10 upload-queue, RX reorder and beacon/TIM fixes; and r11
TX-stall gating, resume safety paths and queue-counter diagnostics.
On 2026-10-02, the driver was renamed RTL88WiFi, its controller/interface
classes and bundle identity were renamed, and its version restarted at 1.0.0.
The prior 2.0.1 builds were development derivatives, not upstream releases.
See the Git history and `CHANGELOG.md` for this repository's changes.

## Third-party work

- AirPort_RTW88: xnoah222 / Realtek-AirPort-Family, the starting native AirPort
  implementation. Its original credits are preserved in
  [docs/upstream-credits.md](docs/upstream-credits.md).
- Feixiao: https://github.com/thegwchr/Feixiao, the underlying macOS port.
- Linux rtw88: Realtek, Linux kernel developers and rtw88 contributors;
  https://github.com/thegwchr/rtw88-stable is the Linux source snapshot used by
  the build. Original file notices and `driver/rtw88-stable/COPYING` remain.
- OpenIntelWireless / itlwm / AirportItlwm: implementation references for
  native IO80211 integration, as described in the upstream credits.
- MacKernelSDK and Apple interfaces: original per-file notices and
  `driver/RTL88WiFi/MacKernelSDK/LICENSE.txt` remain.
- Firmware files retain their original notices in
  `driver/RTL88WiFi/firmware/README`.

## Distribution terms

The upstream source distribution's GPLv2 license is included as `LICENSE`.
Individual source files retain their SPDX expressions and copyright notices;
the combined derived driver is distributed under GPLv2. This does not
relicense separate SDK, firmware or bundled dependency components.

AMFIPass, IOSkywalkFamily and IO80211FamilyLegacy are separate bundled
dependencies, not RTL88WiFi code. They retain their original identities and
rights. The upstream dependency sources are
https://github.com/kaoskinkae/AMFIPass and
https://github.com/Edwardwich/BCM-WIFI-Sequoia. Apple networking binaries remain
Apple components; inclusion here does not claim ownership or relicense them.

These source credits do not imply affiliation with, endorsement by, or
maintenance responsibility for RTL88WiFi on the part of upstream authors.
