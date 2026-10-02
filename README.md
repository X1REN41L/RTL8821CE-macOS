# RTL8821CE-macOS — native Wi-Fi for Realtek rtw88 cards on Hackintosh

Native AirPort-style Wi-Fi for the **Realtek RTL8821CE** on macOS Sonoma, using
**AirPort_RTW88 2.0.1**. The card shows up as a normal Wi-Fi interface in the
menu bar and System Settings, with no client app. SIP stays enabled.

2.0.1 is my fork of xnoah222's AirPort_RTW88 2.0.0 (Realtek-AirPort-Family).
It fixes WPA2 disconnects, slow throughput, sleep/wake reconnects and several
memory-safety bugs. I use it daily on my own machine.

> [!WARNING]
> This is an experimental kernel extension, tested on **one laptop with one
> router**. Before changing your EFI, keep a working copy of your EFI on a USB
> stick so you can still boot.

---

## Supported Wi-Fi chips

Only PCIe cards are supported. USB and SDIO Realtek adapters are **not**.

| Chip | PCI ID | Status with 2.0.1 |
|---|---|---|
| **RTL8821CE** | `10ec:c821`, `10ec:b821` | ✅ **Tested**: daily use |
| RTL8822BE | `10ec:b822` | ⚠️ Matched by the kext and firmware included, **untested** |
| RTL8822CE | `10ec:c822`, `10ec:c82f` | ⚠️ Matched by the kext and firmware included, **untested** |

To find your card's ID on macOS, run
`ioreg -l | grep -iE '"vendor-id"|"device-id"'`, or look in Hackintool's
**PCIe** tab. On Linux or Windows, use `lspci -nn` or Device Manager →
Hardware IDs. Look for vendor `10ec`.

Bluetooth on these combo cards is a separate USB device, and this project
does **not** cover it.

## Supported macOS versions

| macOS | Status with 2.0.1 |
|---|---|
| **Sonoma 14.8.9 (23J631)** | ✅ **Tested**: this guide |
| Sonoma 14.4 and later | ⚠️ Expected to work, untested |
| Sequoia 15, Tahoe 26 | ⚠️ Upstream 2.0.0 supports these with the same setup; 2.0.1 is untested |
| Ventura 13.7.7 – 13.7.8 | ⚠️ Upstream uses only `AirPort_RTW88.kext` here (no Skywalk/AMFIPass, no block); untested |
| Monterey 12 and older | ❌ Not supported by this kext |

If you test 2.0.1 on another chip or macOS version, please open an issue with
the result (see [Reporting results](#reporting-results)).

---

## What works

- WPA2-Personal (AES/CCMP)
- WPA3/WPA2 **transition** mode (connects as WPA2)
- Open networks
- 2.4 GHz and 5 GHz, including 80 MHz VHT on 5 GHz
- Scanning, the Wi-Fi menu with signal strength, joining networks from the
  menu, saved networks, auto-join and switching between networks
- Group-key rekeys (no drops)
- Sleep/wake (lid close and Apple menu → Sleep) with automatic reconnect
- Works with SIP enabled; no root patching required

## What doesn't work / known issues

- ❌ **WPA3-only (SAE)** networks
- ❌ **WPA2/WPA3 Enterprise** (802.1X)
- ❌ **Joining hidden SSIDs**
- ❌ AirDrop, Continuity, Sidecar, Handoff and other AWDL features
- ❌ Bluetooth (separate device, not covered)
- ❔ WPA2 with TKIP (mixed mode) is untested
- Cosmetic: after **some** wakes, macOS marks the connected network as
  "hidden" in its saved profile. The connection itself is fine, and the next
  normal join clears it.
- On 2.4 GHz under a full-speed upload, the driver briefly throttles TX.
  This is flow control, not a hang.

## Results

Measured with `networkQuality` bound to the Wi-Fi interface. My internet line
is capped at 100 Mbps.

| | Down | Up |
|---|---|---|
| Stock 2.0.0, WPA2, 5 GHz | 7.2 Mbps | 20.7 Mbps |
| **2.0.1, WPA2, 5 GHz (80 MHz)** | **92.1 Mbps** | **98.6 Mbps** |
| **2.0.1, 2.4 GHz** | **41.7 Mbps** | **58.2 Mbps** |
| Ethernet on the same line (reference) | 82.7 Mbps | 96.3 Mbps |

---

## Installation (macOS Sonoma, OpenCore)

You need a working OpenCore EFI that already boots macOS and loads
**Lilu.kext**. Use [ProperTree](https://github.com/corpnewt/ProperTree) to
edit `config.plist`.

### 1. Back up your EFI

Copy your whole `EFI` folder to a USB stick, and check that you can boot from
that stick. If Wi-Fi setup goes wrong, boot from the stick and restore the
folder.

### 2. Copy the kexts

Download this repository (**Code → Download ZIP**). Copy these four kexts from
[`Kexts/`](Kexts) to `EFI/OC/Kexts/`:

| Kext | Version | Purpose |
|---|---|---|
| `AMFIPass.kext` | 1.4.1 | Lets the unsigned Wi-Fi kexts load with SIP enabled |
| `IOSkywalkFamily.kext` | 1.0 | Older Skywalk networking stack needed by the legacy Wi-Fi family |
| `IO80211FamilyLegacy.kext` | 1200.12.2b1 | Legacy Apple Wi-Fi family the driver plugs into |
| `AirPort_RTW88.kext` | **2.0.1** | The Realtek driver (firmware is built in) |

If you already use other Wi-Fi kexts (itlwm, AirportItlwm, a Broadcom
patch set), disable them.

### 3. Add the kexts to `Kernel → Add`

Add them **after Lilu**, in exactly this order. Every entry uses
`Arch = Any`, `MinKernel = 23.0.0`, `MaxKernel` empty, and `Enabled = True`:

| # | BundlePath | ExecutablePath | PlistPath |
|---|---|---|---|
| 1 | `AMFIPass.kext` | `Contents/MacOS/AMFIPass` | `Contents/Info.plist` |
| 2 | `IOSkywalkFamily.kext` | `Contents/MacOS/IOSkywalkFamily` | `Contents/Info.plist` |
| 3 | `IO80211FamilyLegacy.kext` | `Contents/MacOS/IO80211FamilyLegacy` | `Contents/Info.plist` |
| 4 | `AirPort_RTW88.kext` | `Contents/MacOS/AirPort_RTW88` | `Contents/Info.plist` |

`IO80211FamilyLegacy.kext` contains an `AirPortBrcmNIC.kext` plugin. **Do not
add it.** It is only for Broadcom cards. (ProperTree's OC Snapshot adds it
automatically; delete or disable that entry afterwards.)

### 4. Block the built-in IOSkywalkFamily (`Kernel → Block`)

Add one entry:

| Key | Value |
|---|---|
| Identifier | `com.apple.iokit.IOSkywalkFamily` |
| Strategy | `Exclude` |
| MinKernel | `23.0.0` |
| MaxKernel | *(empty)* |
| Arch | `Any` |
| Enabled | `True` |
| Comment | `Allow legacy Wi-Fi / block native Skywalk` |

Without this block, macOS loads its own Skywalk stack and the Wi-Fi kexts
cannot attach.

[`docs/opencore-wifi-snippet.plist`](docs/opencore-wifi-snippet.plist)
contains steps 3 and 4 as plist XML that you can copy into ProperTree.

### 5. Security settings

My working setup uses these:

- `Misc → Security → SecureBootModel = Disabled`. The standard Sonoma
  legacy-Wi-Fi setup uses this, and it is what I tested.
- SIP **enabled**: `csr-active-config = 00000000`. AMFIPass handles the
  unsigned kexts, so SIP does not need to be disabled.
- No extra boot-args are needed for Wi-Fi.

### 6. Validate and reboot

1. Save `config.plist` and run OpenCore's `ocvalidate` on it. It should
   report no issues.
2. Reboot into macOS.
3. After login, open the Wi-Fi menu, pick your network and enter the
   password.

### 7. Check that it loaded

```sh
kextstat | grep -E 'rtw88|IO80211FamilyLegacy|IOSkywalk|AMFIPass'
```

You should see `com.rtw88.airport (2.0.1)` together with
`IO80211FamilyLegacy`, `IOSkywalkFamily` and `AMFIPass`. Under
**System Settings → Network**, Wi-Fi should show as connected.

### Recommended power settings (laptops)

Power Nap's dark wakes can make lid sleep look unreliable on OpenCore laptops
(the power LED stays solid, or the lid only locks the screen). These settings
fixed it on my machine:

```sh
sudo pmset -a powernap 0 proximitywake 0 standby 0 hibernatemode 0
```

## Troubleshooting

| Symptom | Check |
|---|---|
| No Wi-Fi interface at all | Is the `Kernel → Block` entry present and enabled? Are all four kexts enabled, in the right order, with `MinKernel 23.0.0`? Run `kextstat` as in step 7. |
| Boot stops / kernel panic right after adding the kexts | Boot from your backup USB EFI. Check that `AirPortBrcmNIC.kext` is **not** in `Kernel → Add` and that `SecureBootModel` is `Disabled`. |
| Networks are visible but joining fails | WPA3-only, Enterprise and hidden networks are not supported. Set the router to WPA2-Personal (AES) or WPA2/WPA3 transition mode. |
| Driver log | `ioreg -l -w0 \| grep DiagnosticLog` shows the driver's internal log ring. It contains no keys or packet payloads. |

## Reporting results

Please open an issue with:

- your chip and PCI ID, laptop/board, and macOS version
- the router's security mode (WPA2, WPA2/WPA3, …) and band
- what works and what doesn't, including sleep/wake
- the `kextstat` line from step 7

---

## What changed in 2.0.1 (vs. AirPort_RTW88 2.0.0)

- **WPA2 handshake:** re-sends M4 on a duplicate M3, keeps the SNonce stable
  across M1 retries, installs keys idempotently (CCMP packet numbers are
  kept), uses correct M2/M4 fields, and supports group-key rekeys. This fixed
  the deauth reason 15 disconnects.
- **Memory safety:** a larger sk_buff control block (TX metadata overran it),
  bounds checks in firmware decompression, and station lifetime fixes.
- **Rates:** parses the AP's HT/VHT capabilities and intersects them with the
  chip's (1T1R). This took 5 GHz from ~7 Mbps to line rate.
- **macOS integration:** correct disconnect reasons. This fixes
  "Dropped Connection reason=0" auto-join loops after manual joins and at
  sleep. Also: Sonoma-ABI answers for CURRENT_NETWORK and AP_IE_LIST, and the
  SSID is kept in scan results (no phantom "Hidden Network" entry).
- **RX hardening:** drops undecrypted or plaintext frames on a protected link,
  trims CCMP/TKIP trailers, and adds the FragAttacks A-MSDU check.
- **Diagnostics:** an in-kernel log ring readable from IORegistry
  (`DiagnosticLog`).

The full source change is in
[`source/AirPort_RTW88-2.0.1.patch`](source/AirPort_RTW88-2.0.1.patch). See
[`source/BUILD.md`](source/BUILD.md) to build it yourself.

## My test setup

- HP 15-da0003tu laptop, Intel i3-8130U, UHD 620, SMBIOS `MacBookPro14,1`
- OpenCore 1.0.7, macOS Sonoma 14.8.9 (23J631)
- Realtek RTL8821CE (`10ec:c821`)
- Mercusys router, WPA2/WPA3 transition mode, 2.4 + 5 GHz

## Credits

- **xnoah222**: [Realtek-AirPort-Family](https://github.com/xnoah222/Realtek-AirPort-Family)
  / AirPort_RTW88 2.0.0, the base of this build
- **thegwchr**: [Feixiao](https://github.com/thegwchr/Feixiao) and
  [rtw88-stable](https://github.com/thegwchr/rtw88-stable), the macOS rtw88 port
- The Linux **rtw88** developers and Realtek
- **OpenIntelWireless** (itlwm/AirportItlwm), used as references by upstream
- **Acidanthera** (Lilu, OpenCore), and the AMFIPass / IOSkywalkFamily /
  IO80211FamilyLegacy work used by the OpenCore Legacy Patcher community

## Old development snapshot

The previous contents of this repository were my own unfinished rtw88
reconstruction (the `rtw88ctl` driver), which had a TX throughput failure.
They are kept unchanged in [`archive/`](archive).
