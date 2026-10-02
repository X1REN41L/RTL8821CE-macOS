# RTL88WiFi

Native macOS Wi-Fi for Realtek **RTL8821CE, RTL8822BE and RTL8822CE** PCIe cards
on Hackintosh. The card works like a Mac's AirPort card: it shows up in the
Wi-Fi menu, auto-joins and reconnects after sleep. SIP stays enabled, and no
client app is needed.

> [!WARNING]
> Kernel extension in active development. Keep a bootable EFI backup on USB.

<p align="center">
  <img src="docs/images/speedtest-2.0.1.png" alt="RTL8821CE speed test: 93.40 Mbps down, 92.45 Mbps up" width="380">
</p>

On a 100 Mbps line, RTL8821CE on Sonoma reaches 86–93 Mbps down and 89–105 Mbps
up. The link held through load tests and sleep/wake. Before these fixes, the
same card managed 7 Mbps and kept disconnecting.

## Compatibility

| Chip | PCI ID | Status |
|---|---|---|
| RTL8821CE | `10ec:c821`, `10ec:b821` | ✅ Verified |
| RTL8822BE | `10ec:b822` | 🟡 Supported, needs reports |
| RTL8822CE | `10ec:c822`, `10ec:c82f` | 🟡 Supported, needs reports |

| macOS | Status |
|---|---|
| Sonoma 14 | ✅ Verified on 14.8.9 |
| Sequoia 15 / Tahoe 26 | 🟡 Same setup, needs reports |
| Ventura 13.7.7–13.7.8 | 🟡 Add only `RTL88WiFi.kext` (no other kexts or Block entry), needs reports |
| Monterey and older | ❌ |

PCIe only; USB and SDIO adapters are not supported. Confirmed machines are
listed in [docs/COMPATIBILITY.md](docs/COMPATIBILITY.md).

**Check your machine** (read-only, before or after installing):

```sh
bash tools/rtl88wifi-check.sh           # chip, macOS, kexts, link
bash tools/rtl88wifi-check.sh --speed   # plus ping and networkQuality
```

It ends with a report block (without MAC, IP or network name) for a
[compatibility report](../../issues/new?template=compatibility-report.yml).

## Features

**Works:** WPA2-Personal, WPA2/WPA3 transition mode (connects as WPA2), open
networks, 2.4 and 5 GHz (80 MHz), Wi-Fi menu and auto-join, network switching,
group rekeys, sleep/wake.

**Doesn't work yet:** WPA3-only, Enterprise, hidden networks, AirDrop and
Continuity (AWDL). Bluetooth is a separate device and is not covered. TKIP is
untested.

**Known issues:**
- Heavy parallel uploads can overflow macOS's output queue (1–4% drops in
  `networkQuality`). Speed stays at line rate.
- After some wakes, macOS may label the network as "hidden". The connection
  is not affected.

## Setup (OpenCore)

You need a working OpenCore EFI with Lilu. Back up your EFI to USB first.

1. **Copy the kexts.** Copy `AMFIPass`, `IOSkywalkFamily`, `IO80211FamilyLegacy`
   and `RTL88WiFi` from [`Kexts/`](Kexts) to `EFI/OC/Kexts/`. Disable any other
   Wi-Fi kext.
2. **`Kernel → Add`.** Add the kexts after Lilu, in that order. Executable path:
   `Contents/MacOS/<name>`. For each entry set `MinKernel 23.0.0` and
   `Enabled true`.
   Do **not** add the `AirPortBrcmNIC.kext` plugin inside IO80211FamilyLegacy.
3. **`Kernel → Block`.** Add `com.apple.iokit.IOSkywalkFamily`, Strategy
   `Exclude`, `MinKernel 23.0.0`, `Enabled true`.
4. **Security.** Set `SecureBootModel` to `Disabled`. SIP can stay enabled, and
   no boot-args are needed.
5. **Validate, reboot and verify.** Run `ocvalidate`, reboot, join your
   network, then run `bash tools/rtl88wifi-check.sh --speed`.

Steps 2 and 3 are ready to paste from
[docs/opencore-wifi-snippet.plist](docs/opencore-wifi-snippet.plist).

## Troubleshooting

| Problem | Fix |
|---|---|
| No Wi-Fi | Check the Block entry, the kext order and `MinKernel`; run the check script |
| Panic at boot | Boot the USB backup; remove `AirPortBrcmNIC.kext`; set `SecureBootModel` to `Disabled` |
| Can't join | Use WPA2-Personal or WPA2/WPA3 mixed mode |
| Lid closes but the laptop doesn't sleep | `sudo pmset -a powernap 0 proximitywake 0 standby 0 hibernatemode 0` |
| Driver log | `ioreg -l -w0 \| grep DiagnosticLog` (contains no passwords or traffic) |

## Build

```sh
cd driver/RTL88WiFi && make rtl88wifi   # output: build/out/RTL88WiFi.kext
```

Requires the Xcode Command Line Tools and `python3`. Load the kext through
OpenCore, not `make install`. Host tests: [tests/README.md](tests/README.md).
Changes: [CHANGELOG.md](CHANGELOG.md).

## Contributing

The most useful contribution right now is a compatibility report, especially
for RTL8822BE/CE, Sequoia/Tahoe and desktop cards. Pull requests are welcome
for WPA3-only, Enterprise, hidden networks, AWDL and upload drops.

Tested on an HP 15-da0003tu (i3-8130U), OpenCore 1.0.7, macOS 14.8.9.

## License

GPL-2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
