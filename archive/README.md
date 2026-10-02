# RTL8821CE-macOS — Archived Development Snapshot

> **Project status: discontinued / archived.**  
> This repository preserves an unfinished experimental port of Linux `rtw88`
> to macOS, with the RTL8821CE as the primary reconstruction and hardware-test
> target. It is **not production-ready** and still has a severe unresolved TX
> throughput failure.

## Why this archive exists

This repository is a final public snapshot of the development workspace at the
point the project was stopped in September 2026. It keeps the macOS port, the
matching modified Linux `rtw88` reference tree, test scripts, reconstruction
notes, and the exact state of the final diagnostic work so another developer
can continue without repeating the early investigation.

The original Feixiao project is by `thegwchr`:

- https://github.com/thegwchr/Feixiao
- https://github.com/thegwchr/rtw88-stable

This archive contains substantial reconstruction/debugging work on top of
those sources. Third-party code retains its own licensing and copyright terms.

## Target hardware used during reconstruction

The main hardware target was:

- Realtek **RTL8821CE** PCIe Wi-Fi (`10ec:c821`)
- Intel 8th-generation mobile platform
- macOS Sonoma 14.8.9 / Darwin 23.6.0
- OpenCore-based Hackintosh test environment
- x86_64 kext build

The codebase also contains support paths for other PCIe `rtw88` chipsets, but
only RTL8821CE received the deep hardware validation documented here.

## What works

The project reached a state where the RTL8821CE could:

- initialize as a PCIe device;
- load firmware;
- scan 2.4 GHz and 5 GHz networks;
- report RSSI;
- associate and connect to WPA2 networks;
- obtain DHCP connectivity;
- receive data at useful speeds;
- use the `rtw88ctl` command-line utility for scan/connect/status/control;
- survive repeated connect/disconnect testing in the validated baseline.

A stable receive-side local iperf3 control was repeatedly around **40–45
Mbit/s** in the test environment.

## What does not work

Sustained outbound Wi-Fi throughput remains severely broken.

Typical local Mac-to-peer iperf3 behavior:

- initial bursts around 1–6 Mbit/s;
- collapse after roughly 10–16 seconds;
- long zero-throughput intervals;
- TCP congestion window collapsing to a few kilobytes;
- final throughput around **0.7–0.8 Mbit/s**;
- thousands of TCP retransmissions.

One final controlled 30-second run produced:

```text
2.62 MBytes transferred
733 Kbit/s
7020 TCP retransmissions
```

The reverse direction remained tens of Mbit/s, so the failure is strongly
asymmetric.

## Most important final finding

The final direct TX-path instrumentation ruled out the main PCI-side failure
hypotheses.

During the failing bulk TX interval:

- 1542-byte data descriptors continued to be submitted;
- the hardware TX read pointer continued advancing;
- software reclaim continued advancing;
- the BE ring retained substantial free space;
- `qstop` remained clear;
- `TXDMA_STATUS` remained zero;
- DMA mapping failures remained zero;
- when TCP stopped providing new data, outstanding descriptors drained
  normally.

DMA accounting also remained internally consistent:

```text
active DMA mappings - outstanding TX mappings = 1025
```

The fixed 1025 baseline corresponded to RX/static mappings; incremental active
mappings tracked outstanding TX descriptors exactly.

### What that means

The host-to-NIC PCI/DMA/reclaim pipeline is not the sustained bottleneck.
Descriptor reclaim only proves that the NIC consumed the descriptor; it does
**not** prove that the corresponding 802.11 frame was successfully ACKed or
BlockAcked over the air.

The unresolved defect therefore appears to be in the **over-air 802.11 / Wi-Fi
firmware TX semantics after descriptor submission**, rather than a frozen PCI
ring.

## Strongest remaining hypothesis: TX BA / A-MPDU handling

Static comparison with the pinned Linux implementation found that the macOS
port does not reproduce mac80211's complete TX Block Ack state machine.

Linux/mac80211 tracks, among other things:

- per-TID BA state;
- requested vs operational state;
- dialog token;
- response timeout;
- starting sequence number;
- negotiated BA window size;
- stop transitions;
- BAR/recovery state;
- operational retransmission/window accounting.

The port instead uses a simplified custom path for TID 0:

- sends an ADDBA request after key installation;
- accepts a successful TID-0 ADDBA response;
- sets a single `_txBaActive` boolean;
- marks subsequent QoS TID-0 frames with `IEEE80211_TX_CTL_AMPDU`;
- clears the flag on matching DELBA.

Confirmed semantic gaps include missing response-token validation, negotiated
TX BA window enforcement, response/session timers, explicit pending-to-
operational coordination, per-TID session state, and BAR recovery state.

The hardware diagnostics showed that essentially every normal bulk data frame
was AMPDU-marked. This made the custom BA/A-MPDU implementation the strongest
remaining hypothesis, but **it was not proven to be the root cause**.

## Planned next experiment that was never completed

The next justified A/B test was deliberately narrow:

1. Keep QoS TID 0.
2. Keep WPA2/CCMP encryption unchanged.
3. Keep sequence and CCMP PN handling unchanged.
4. Keep firmware rate adaptation unchanged.
5. Keep HT/VHT, bandwidth, SGI, queue selection and PCI handling unchanged.
6. Suppress TX ADDBA negotiation.
7. Never set `IEEE80211_TX_CTL_AMPDU` for normal data.
8. Send ordinary individually acknowledged QoS data frames.

Interpretation would have been simple:

- If TX recovered, focus on implementing a correct per-TID BA/A-MPDU state
  machine and negotiated-window behavior.
- If TX remained around 0.7–0.8 Mbit/s, move next to firmware rate adaptation /
  retry behavior versus encrypted non-aggregated TX.

**This non-A-MPDU isolation candidate was not built or tested.**

## Source state preserved here

The public archive is a sanitized snapshot, not a continuation of the original
nested Git histories. The exact source points used to make it were:

| Component | Commit |
| --- | --- |
| Feixiao working source | `cf94a13eb5315baba577319f0c7a181ed5d99760` |
| Modified `rtw88-stable` source | `1721c751ee7e7b1c38ae187cc703b20ac3e3ca85` |
| Pinned Linux reference base | `d029a677c49266fad86750714eb5612becd134d3` |
| Last fully hardware-validated functional baseline | `d2b47a096cbb905c2e486fb57928aa2c89b2e069` |
| Vendored MacKernelSDK snapshot | `7af1933c27aefcbdf4809ee44478829aad30f9c1` |

The two local driver commits above the pinned Linux reference were diagnostic
changes:

```text
63ad004  diag: snapshot TX ring on RX tag mismatch
1721c75  diag: sample active BE TX submit and reclaim
```

The Feixiao source at the archived HEAD also contains diagnostic instrumentation
and documentation commits. Do not confuse the archive HEAD with the last clean
functional baseline.

### Final diagnostic kext identity

```text
SHA-256:
5876038c4c0b0485316bcaf03cd4186b58ea5dab8ecbf8da221faff0259a9732

Mach-O UUID:
F34202C9-EA4E-393D-B4E7-5BD377474F9E
```

This identity corresponds to the direct TX-path diagnostic candidate, **not a
throughput fix**.

## Important fixes already completed

The reconstruction work before the final TX investigation included fixes or
validation around:

- `sk_buff::cb` layout sizing;
- VIF allocation via `hw->vif_data_size`;
- completion timeout locking;
- XNU wait/thread interruptibility;
- station lookup/registry support;
- repeated WPA2 M3 handling and M4 retransmission without key/PN reset;
- EAPOL state handling;
- firmware TX reports for management/handshake traffic;
- firmware prerequisite and empty-input validation;
- firmware decompression sizing;
- association-response lifetime handling;
- BSS/security merge behavior;
- auth/assoc validation;
- stable SNonce/PTK behavior across M1 retransmission;
- RSSI preservation when hardware reports `RX_FLAG_NO_SIGNAL_VAL`;
- active PCI compatibility/prototype validation;
- async teardown/quiescing work;
- AP peer capability parsing for firmware rate adaptation.

The AP peer-capability fix was real and remains worth preserving, but hardware
testing showed it was not sufficient to resolve the sustained TX failure.

## RX tag warning note

The driver can emit:

```text
pci bus timeout, check dma status
```

Despite the wording, the investigated path was an **RX descriptor DMA-tag
sequence mismatch**, not proof of a TX DMA timeout.

The expected and observed RX tag became persistently desynchronized during
some tests, while the RX path could still sustain roughly 40–45 Mbit/s and the
BE TX ring could remain healthy or empty. Treat this as a separate correctness
issue; do not use the warning alone as evidence of a TX-ring stall.

## Repository layout

```text
.
├── README.md
├── Feixiao/
│   ├── src/                    # macOS kext/compatibility code
│   ├── ctl/                    # rtw88ctl
│   ├── docs/RECONSTRUCTION.md  # detailed investigation history
│   ├── firmware/README         # firmware acquisition instructions
│   ├── MacKernelSDK/           # vendored SDK snapshot
│   └── Makefile
├── rtw88-stable/               # exact modified Linux source snapshot
└── Feixiao-Test-Tools/         # historical hardware regression scripts
```

The original nested `.git` directories, local build products, macOS metadata,
and private network credentials were intentionally excluded from this public
archive.

## Building

The build expects the directory relationship preserved in this repository:

```text
repo/
├── Feixiao/
└── rtw88-stable/
```

Realtek firmware binaries are intentionally not committed. Follow:

```text
Feixiao/firmware/README
```

Then build from the Feixiao directory:

```sh
cd Feixiao
make all
```

Expected outputs are placed under:

```text
Feixiao/build/out/
```

including `rtw88.kext` and `rtw88ctl`.

## Basic control utility usage

```sh
./build/out/rtw88ctl status
./build/out/rtw88ctl scan -w 5
./build/out/rtw88ctl list
./build/out/rtw88ctl connect "SSID" "PASSWORD"
./build/out/rtw88ctl disconnect
```

This is experimental kernel code. Use an external/test OpenCore EFI rather
than replacing a known-good boot environment while developing.

## Test scripts

`Feixiao-Test-Tools/` contains historical regression scripts. Local test
credentials were removed for the public archive. Supply test-specific values
through environment variables, for example:

```sh
export RTW_TEST_SSID='your-test-ssid'
export RTW_TEST_PASSWORD='your-test-password'
export RTW_TEST_BSSID='aa:bb:cc:dd:ee:ff'
```

The scripts also contain candidate-specific expected UUIDs and should be
reviewed before reuse on a new build.

## Where to continue

A developer resuming this work should start with:

1. Read `Feixiao/docs/RECONSTRUCTION.md`.
2. Reproduce the last functional baseline on RTL8821CE.
3. Confirm the current direct TX-path result rather than reopening PCI/DMA
   hypotheses without contrary evidence.
4. Build the planned **non-A-MPDU isolation candidate** as a one-variable test.
5. If that recovers TX, implement proper per-TID BA state and negotiated-window
   semantics instead of keeping aggregation disabled.
6. If it does not recover TX, instrument actual over-air ACK/retry/rate behavior
   and isolate firmware RA from encrypted non-aggregated TX.

Normal data currently lacks enough firmware TX-report visibility to tell the
host whether a reclaimed descriptor was actually ACKed/BlockAcked over the
air. Improving that observability would also be useful.

## Safety / expectations

- This driver is unfinished.
- Kernel panics, connectivity loss and boot failures are possible.
- Sleep/wake was not comprehensively validated.
- Do not install it as the only copy of a boot-critical kext.
- Keep a known-good EFI or other recovery path.
- The archive should not be described as a finished RTL8821CE macOS driver.

## Credits

This work builds on:

- Realtek and Linux `rtw88` contributors;
- the original Feixiao project by `thegwchr`;
- Acidanthera MacKernelSDK;
- OpenIntelWireless/itlwm as an implementation reference;
- FreeBSD/LinuxKPI approaches used as compatibility references.

See source files and bundled upstream trees for their respective copyright and
license notices.

---

**Final status:** association and RX are functional on the tested RTL8821CE,
but sustained TX remains unresolved. The project was intentionally stopped
before the planned non-A-MPDU isolation experiment.
