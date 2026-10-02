# RTL88WiFi

**Native macOS Wi-Fi for Realtek RTL8821CE, RTL8822BE and RTL8822CE PCIe cards
on Hackintosh laptops and desktops.**

The card works like a real Mac's AirPort card. It shows up in the Wi-Fi menu and
System Settings, remembers networks, auto-joins, and reconnects after sleep.
You don't need a client app, and SIP stays enabled.

| | |
|---|---|
| **Version** | 1.0.0 (`io.github.x1ren41l.RTL88WiFi`) |
| **Verified on hardware** | RTL8821CE, macOS Sonoma 14.8.9 |
| **Chips the kext matches** | RTL8821CE, RTL8822BE, RTL8822CE (PCIe) |
| **Check your machine** | `bash tools/rtl88wifi-check.sh` ([details](#check-your-machine)) |
| **Report your result** | [Compatibility report](../../issues/new?template=compatibility-report.yml) |

> [!WARNING]
> This is a kernel extension in active development. Keep a bootable copy of
> your current EFI on a USB stick before you change anything.

---

## Results

<p align="center">
  <img src="docs/images/speedtest-2.0.1.png" alt="Speed test on RTL8821CE: 93.40 Mbps down, 92.45 Mbps up, 7 ms ping" width="420"><br>
  <b>RTL8821CE on macOS Sonoma: 93.4 Mbps down / 92.5 Mbps up on a 100 Mbps line (earlier build of this driver).</b>
</p>

RTL88WiFi 1.0.0 on the test laptop (RTL8821CE, 5 GHz channel 36, 100 Mbps
line, 2026-10-02):

| Test | Result |
|---|---|
| Connection over ~15 minutes of load and idle | No drops |
| Idle ping to the router, 480 packets | 0% loss, 4.6–6.6 ms average |
| `networkQuality` download | 86.5–86.9 Mbps |
| `networkQuality` upload | 89.4–105.1 Mbps |
| 4 parallel 40 MB uploads + 4,000 UDP probes | 0.15–0.55% UDP loss |
| Sleep / wake (tested on the preceding build, same wake code) | Reconnects on its own in about 3–5 seconds |

Ethernet on the same line measured 82.7 down / 96.3 up, so Wi-Fi runs at full
line speed. Before the fixes in this driver, the same card managed 7.2 Mbps
down, kept dropping the connection, and lost about 25% of pings under load.

---

## Compatibility

PCIe cards only. USB and SDIO Realtek adapters are **not** supported.

| Chip | PCI ID | Status |
|---|---|---|
| **RTL8821CE** | `10ec:c821`, `10ec:b821` | ✅ Verified (daily use) |
| RTL8822BE | `10ec:b822` | 🟡 Matched by the kext, firmware included, needs a report |
| RTL8822CE | `10ec:c822`, `10ec:c82f` | 🟡 Matched by the kext, firmware included, needs a report |

| macOS | Status |
|---|---|
| **Sonoma 14.8.9** | ✅ Verified |
| Sonoma 14.4 and later | 🟡 Same setup, needs a report |
| Sequoia 15 / Tahoe 26 | 🟡 Same setup, needs a report |
| Ventura 13.7.7 – 13.7.8 | 🟡 Use only `RTL88WiFi.kext` (skip the other three kexts and the Block entry), needs a report |
| Monterey 12 and older | ❌ Not supported |

Every confirmed machine is listed in
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md). If your chip or macOS version
is marked 🟡, your report moves it to ✅ for everyone.

### Check your machine

Run the check script from this repository. It is read-only and changes nothing.

```sh
bash tools/rtl88wifi-check.sh           # before installing: is my chip and macOS suitable?
bash tools/rtl88wifi-check.sh --speed   # after installing: is it loaded, connected and fast?
```

It checks:

- your macOS version;
- that a supported Realtek chip is present (by PCI ID);
- that the required kexts are loaded and no second Wi-Fi driver is;
- the link state, signal strength and default route;
- with `--speed`, a router ping and a `networkQuality` run.

At the end it prints a report block without MAC addresses, IP addresses or
network names. Paste that block into a
[compatibility report](../../issues/new?template=compatibility-report.yml).

You can also find the chip ID by hand. On macOS run
`ioreg -l | grep -iE '"vendor-id"|"device-id"'`. On Windows use Device Manager →
Hardware IDs, and on Linux run `lspci -nn`. Realtek's vendor ID is `10ec`.

---

## What works

- WPA2-Personal (AES), and WPA3/WPA2 **transition** mode (connects as WPA2)
- Open networks
- 2.4 GHz and 5 GHz (80 MHz on 5 GHz)
- Wi-Fi menu, signal strength, joining, saved networks, auto-join, switching networks
- Router key changes (group rekeys) without disconnects
- Sleep/wake (lid and Apple menu → Sleep), with automatic reconnect
- SIP enabled, no root patching

## What doesn't work yet

- ❌ WPA3-only (SAE) networks
- ❌ WPA2/WPA3 Enterprise (work/school logins)
- ❌ Joining hidden networks
- ❌ AirDrop, Continuity, Sidecar, Handoff (AWDL)
- ❌ Bluetooth (a separate USB device on these cards; not covered here)
- ❔ WPA2 with TKIP is untested

## Known issues

- **Heavy parallel uploads.** Under sustained multi-stream upload (for example
  `networkQuality` or several large uploads at once), macOS's 256-packet
  output queue can still overflow and drop some packets. Throughput stays at
  line rate, and TCP recovers. Results vary a lot from run to run: in the
  release check, `networkQuality` lost 1.0–3.8% of offered packets at the
  queue. In one earlier run of the four-upload test, far more were dropped
  while goodput still held.
- **"Hidden network" label.** After some wakes or network switches, macOS can
  label your network as hidden in Wi-Fi settings. The connection itself is not
  affected. 1.0.0 keeps the beacon information macOS uses for this check; the
  label did not appear after the tested wake on the preceding build.
- **2.4 GHz full-speed upload.** The driver briefly throttles sending. This is
  flow control, not a freeze.

---

## Setup guide (OpenCore)

### What you need

- A working OpenCore EFI that already boots macOS and loads **Lilu.kext**
- Any plist editor for `config.plist`
- This repository: **Code → Download ZIP**

### Step 1: back up your EFI

Copy your whole `EFI` folder to a USB stick, and check that you can boot from
it. If anything goes wrong, boot from the stick and copy the folder back.

### Step 2: copy the kexts

Copy these four folders from [`Kexts/`](Kexts) into `EFI/OC/Kexts/`:

| Kext | Version | What it does |
|---|---|---|
| `AMFIPass.kext` | 1.4.1 | Lets the Wi-Fi kexts load with SIP enabled |
| `IOSkywalkFamily.kext` | 1.0 | Older Apple networking stack needed by the legacy Wi-Fi family |
| `IO80211FamilyLegacy.kext` | 1200.12.2b1 | Legacy Apple Wi-Fi family the driver plugs into |
| `RTL88WiFi.kext` | **1.0.0** | The Realtek driver (firmware is built in) |

Remove or disable every other Wi-Fi kext you were using. Only one Wi-Fi driver
may be enabled for the card.

### Step 3: `Kernel → Add`

Add the four kexts **after Lilu**, in exactly this order:

| # | BundlePath | ExecutablePath | PlistPath |
|---|---|---|---|
| 1 | `AMFIPass.kext` | `Contents/MacOS/AMFIPass` | `Contents/Info.plist` |
| 2 | `IOSkywalkFamily.kext` | `Contents/MacOS/IOSkywalkFamily` | `Contents/Info.plist` |
| 3 | `IO80211FamilyLegacy.kext` | `Contents/MacOS/IO80211FamilyLegacy` | `Contents/Info.plist` |
| 4 | `RTL88WiFi.kext` | `Contents/MacOS/RTL88WiFi` | `Contents/Info.plist` |

For every entry, set `Arch = Any`, `MinKernel = 23.0.0`, leave `MaxKernel`
empty, and set `Enabled = True`.

> [!IMPORTANT]
> `IO80211FamilyLegacy.kext` contains an `AirPortBrcmNIC.kext` plugin. **Do
> not add it**, because it is only for Broadcom cards. Snapshot tools add it
> automatically, so delete that entry afterwards.

### Step 4: `Kernel → Block`

Add one entry:

| Key | Value |
|---|---|
| Identifier | `com.apple.iokit.IOSkywalkFamily` |
| Strategy | `Exclude` |
| MinKernel | `23.0.0` |
| MaxKernel | *(empty)* |
| Arch | `Any` |
| Enabled | `True` |

Without this block, macOS loads its own networking stack and Wi-Fi won't
appear.

**Shortcut:** [`docs/opencore-wifi-snippet.plist`](docs/opencore-wifi-snippet.plist)
contains steps 3 and 4, ready to copy into your `config.plist`.

### Step 5: security settings

- `Misc → Security → SecureBootModel` = `Disabled`
- SIP can stay **enabled** (`csr-active-config` = `00000000`)
- No extra boot-args are needed

### Step 6: validate and reboot

1. Save `config.plist` and run OpenCore's `ocvalidate` on it. It should report
   no issues.
2. Reboot into macOS.
3. Open the Wi-Fi menu, pick your network and enter the password.

### Step 7: verify

```sh
bash tools/rtl88wifi-check.sh --speed
```

You should see `io.github.x1ren41l.RTL88WiFi (1.0.0) loaded`, an active
interface, and no failures. Then please
[send a compatibility report](../../issues/new?template=compatibility-report.yml),
especially if your chip, laptop or macOS version is not listed yet.

### Recommended for laptops

If closing the lid only locks the screen, or the sleep light stops blinking,
turn off Power Nap and its related features. These are macOS dark wakes, not
the Wi-Fi driver:

```sh
sudo pmset -a powernap 0 proximitywake 0 standby 0 hibernatemode 0
```

---

## Troubleshooting

| Problem | What to check |
|---|---|
| No Wi-Fi at all | The `Kernel → Block` entry exists and is enabled; all four kexts are enabled, in order, with `MinKernel 23.0.0`; run `tools/rtl88wifi-check.sh` |
| Panic or boot stops after adding the kexts | Boot from your backup USB. Make sure `AirPortBrcmNIC.kext` is **not** in `Kernel → Add` and `SecureBootModel` is `Disabled` |
| Networks appear but joining fails | WPA3-only, Enterprise and hidden networks aren't supported. Set the router to WPA2-Personal (AES) or WPA2/WPA3 mixed mode |
| Need the driver log | `ioreg -l -w0 \| grep DiagnosticLog` (contains no passwords or traffic); attach it to your issue |

---

## Building from source

The complete driver source is in [`driver/`](driver). You need Xcode or the
Xcode Command Line Tools, and `python3`.

```sh
cd driver/RTL88WiFi
make rtl88wifi
```

The kext is written to `driver/RTL88WiFi/build/out/RTL88WiFi.kext`. The
Realtek firmware in `driver/RTL88WiFi/firmware/` is compressed into the kext
during the build. Use `make rtl88wifi` only: on Sonoma and later the kext must
be loaded by OpenCore, not with `make install` or `make load`.

The five host test suites are described in [tests/README.md](tests/README.md).
Build and identity checks are recorded in
[docs/validation-1.0.0.json](docs/validation-1.0.0.json).

### What 1.0.0 fixes

- **WPA2:** correct handshake retries and key installation, plus group rekeys.
  This fixes the constant disconnects.
- **Speed:** the router's high-speed (HT/VHT) capabilities are read and used.
  This took 5 GHz from about 7 Mbps to line rate.
- **Stability:** memory-safety fixes (buffer overrun, firmware bounds checks,
  station lifetime).
- **macOS integration:** correct disconnect reasons (no auto-join loops after
  manual joins or sleep), Sonoma-format network info, SSIDs kept in scan
  results, beacon TIM kept for the connected network.
- **Security:** undecrypted or plaintext frames on a protected link are
  dropped, and the FragAttacks A-MSDU check is added.
- **RX reorder:** multicast and NoAck QoS traffic bypass the per-TID reorder
  window.
- **Diagnostics:** a built-in log readable via `ioreg` (`DiagnosticLog`),
  including queue drop and stall counters.

---

## Contributing

Compatibility reports are the most useful contribution right now. Each
confirmed chip, laptop or macOS version goes into
[docs/COMPATIBILITY.md](docs/COMPATIBILITY.md). Especially wanted:

- **RTL8822BE / RTL8822CE** cards
- **Sequoia and Tahoe**
- Desktop PCIe cards and other laptop models
- Other routers and security modes

Pull requests are welcome for the open items: WPA3-only (SAE), Enterprise,
hidden networks, AWDL, and drops under heavy parallel uploads.

## Test machine

HP 15-da0003tu laptop (i3-8130U, UHD 620), SMBIOS `MacBookPro15,2`,
OpenCore 1.0.7, macOS Sonoma 14.8.9 (23J631), RTL8821CE, WPA2/WPA3 mixed-mode
router.

## License

GPL-2.0. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
