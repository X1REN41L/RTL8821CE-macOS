# RTL8821CE reconstruction journal

This branch reconstructs the earlier, uncommitted RTL8821CE stabilization work
against a fresh upstream checkout. Historical patches are treated as audit leads,
not as patches to replay. No kext installation, loading, EFI modification, or
other boot-system change is part of this reconstruction phase.

## Baseline provenance

- Reconstruction date: 2026-09-19 (Asia/Dhaka)
- Local branch: `reconstruction/rtl8821ce-20260919`
- Feixiao upstream: `https://github.com/thegwchr/Feixiao.git`
- Feixiao revision: `e963f43188382eced4ef2fa75d19ce4db2315c68`
- Required sibling `rtw88-stable` upstream: `https://github.com/thegwchr/rtw88-stable.git`
- `rtw88-stable` revision: `d029a677c49266fad86750714eb5612becd134d3`
- MacKernelSDK submodule revision: `7af1933c27aefcbdf4809ee44478829aad30f9c1`
- Target: Realtek RTL8821CE (`10ec:c821`), PCIe, `rtw8821c_fw.bin`
- Host: macOS 14.8.9 (23J631), Apple clang 16.0.0 / Xcode Command Line Tools

## Untouched-upstream baseline

- Command: `make all`
- Result: exit status 0; both `build/out/rtw88.kext` and
  `build/out/rtw88ctl` were produced.
- Kext executable UUID: `50E2E120-4E42-3E7D-82CB-0D175E486D05`
- Kext executable size: 1,641,400 bytes
- CLI executable size: 22,640 bytes
- Compiler: Apple clang 16.0.0 (`clang-1600.0.26.6`)
- Firmware input state: no `firmware/*.bin` files were present.
- Important baseline finding: the build still succeeded. Generated
  `src/compat/fw_blobs.c` contained only a zero sentinel and the comment
  `No firmware blobs — add *.bin to firmware/ and rebuild`. This directly
  confirms that untouched upstream can produce an unusable RTL8821CE kext
  without its required firmware.
- The Makefile's parallelism probe printed a sandbox-only `sysctl` permission
  warning. Compilation continued. The build also emitted many compiler
  warnings from the port and vendored driver; no compile or link error occurred.

The proprietary firmware file was not obtained, committed, or redistributed.

## Audit results

### TX metadata versus `sk_buff::cb`

- Status upstream: **present**.
- Evidence: `sk_buff::cb` was 64 bytes. Clang's record-layout dump measured
  `ieee80211_tx_info` at 80 bytes; `sk_buff::list` immediately followed the
  control block. `IEEE80211_SKB_CB()` casts the 64-byte array to the 80-byte
  structure, allowing TX metadata to overwrite the queue links.
- Fix: enlarge the shim control block to 80 bytes and add a C/C++ compile-time
  assertion tying the TX-info size to the control-block capacity.
- Verification: clean `make all` exited 0. The post-change layout dump shows an
  80-byte TX-info structure, an 80-byte control block, and `sk_buff::list`
  beginning after it at offset 136. The new assertion compiled in both the C
  driver units and C++ wrapper units.

### VIF private-data allocation

- Status upstream: **present**.
- Evidence: current `rtw_register_hw()` sets `hw->vif_data_size` to
  `sizeof(struct rtw_vif)`. Clang measured that structure at 176 bytes, while
  `RTW88IEEE80211::start()` allocated only 128 bytes after the aligned
  `ieee80211_vif::drv_priv` offset. Driver writes therefore had 48 bytes less
  backing storage than advertised. The matching `IOFree()` repeated the
  undersized constant.
- Fix: allocate and free the private tail using the driver's authoritative
  `_hw->vif_data_size` value rather than a duplicated constant.
- Verification: clean `make all` exited 0. Allocation and `IOFree()` now use
  the same runtime size, which is 208 + 176 = 384 bytes for this checkout.

### Completion timeout locking

- Status upstream: **present**.
- Evidence: `wait_for_completion_timeout()` unlocked before polling, but on
  timeout it reacquired `c->lock` and returned without unlocking it. A later
  completion or reuse of the object could deadlock on that permanently held
  lock.
- Fix: return from the timeout check while the lock is already released. The
  success path still reacquires the lock, consumes the completion, and unlocks.
- Verification: clean `make all` exited 0. Source-path inspection confirms
  every timeout return now occurs while `c->lock` is released.

### XNU thread interruptibility constants

- Status upstream: **present** in the non-XNU-header fallback declarations.
- Evidence: `iokit_shim.h` defined `THREAD_INTERRUPTIBLE` as 0 and
  `THREAD_UNINT` as 1 in two places. Both the pinned MacKernelSDK and the host
  Kernel.framework define `THREAD_UNINT` as `0x00000000` and
  `THREAD_INTERRUPTIBLE` as `0x00000001`.
- Fix: remove the inaccurate duplicate fallbacks and use the authoritative
  values brought in by the required XNU `kern/thread_call.h` headers.
- Verification: the C preprocessor reports `THREAD_UNINT=0x00000000` and
  `THREAD_INTERRUPTIBLE=0x00000001` from the SDK without redefinition warnings;
  clean `make all` exited 0. The completion change compiled in all users.

### Station registry and lookup

- Status upstream: **present**.
- Evidence: `ieee80211_find_sta()` and
  `ieee80211_find_sta_by_ifaddr()` unconditionally returned `NULL`, and
  `ieee80211_iterate_stations_atomic()` never invoked its callback. The pinned
  driver calls these from RX statistics, beamforming association, beacon-filter
  setup, AMPDU configuration, firmware paths, and station iteration. The kext
  already creates exactly one STA peer for its single active VIF.
- Fix: add a single-active-station registry matching the port's existing
  single-VIF model. Lookups now validate peer MAC, VIF, hardware, and optional
  local MAC as appropriate; iteration reports the registered station. The
  wrapper registers only after successful `sta_add`, preserves registration
  through `sta_remove`, and unregisters before freeing. A failed `sta_add` no
  longer lets association continue with an unusable peer.
- Verification: clean `make all` exited 0. `nm` confirms the lookup and
  register/unregister functions are linked into the kext. Focused source checks
  confirm there are no remaining unconditional-`NULL` station lookups and that
  the register/unregister calls bracket the allocated STA lifetime.

### M3 retransmission and key reinstallation

- Status upstream: **present**.
- Evidence: every valid M3 called `installKey()` for the PTK and optional GTK.
  Replacing the PTK also zeroed `_ccmpTxPn`, so an ordinary M3 retransmission
  reinstalled an already-in-use key and reset the transmit packet number.
- Fix: remember the replay counter of the M3 whose keys were successfully
  installed. An equal replay counter now resends M4 without changing keys or
  packet numbers; an older counter is rejected; a newer counter remains
  eligible for a genuine rekey. Tracking resets with `clearKeys()`.
- Verification: clean `make all` exited 0. Focused control-flow inspection
  confirms the equal-counter branch returns immediately after M4 and cannot
  reach either `installKey()` call or the pairwise PN reset.

### EAPOL after CONNECTED

- Status upstream: **present**.
- Evidence: `deliverDataFrame()` called `handleEAPOL()` only when state was
  exactly `HANDSHAKING`. In `CONNECTED`, a retransmitted M3 was passed upward
  as ordinary Ethernet traffic and the driver never resent M4.
- Fix: dispatch EAPOL frames in both `HANDSHAKING` and `CONNECTED`. Combined
  with the replay-aware M3 path, post-connect retransmissions receive M4 but do
  not reinstall keys.
- Verification: clean `make all` exited 0. The EAPOL branch now covers both
  connection states, while non-EAPOL traffic follows the unchanged delivery
  path.

### M1 retransmission and M2/M4 wire formatting

- Status upstream: **partially fixed, with gaps still present**. Upstream
  commit `05718a7` already supplied the HMAC-SHA1 MIC, corrected M4's Secure
  flag from reserved bit 13 to bit 9, and corrected the EAPOL/outer frame
  lengths. Current source also includes the same selected 22-byte RSN IE in
  the association request and M2. Those repairs were retained unchanged.
- Remaining evidence: the shared builder set the RSN Key Length to 16 in M2
  and M4 and copied SNonce into both messages. The reference
  `wpa_supplicant` RSN implementation sets Key Length to zero for both, copies
  SNonce only into M2, and leaves M4's nonce zero. It also renews SNonce only
  for the first M1 and reuses it for retransmitted M1 frames until M3 succeeds;
  this tree generated a new SNonce/PTK on every M1.
- Fix: emit zero RSN Key Length, put SNonce only in M2, retain SNonce across
  pre-M3 M1 retransmissions, reject M1 replay counters no newer than the
  installed M3, and renew/clear nonce state at handshake boundaries. No M4/key
  installation ordering was changed.
- Verification: the changed C++ translation unit compiled successfully.
  Focused source inspection gives M2 Key Info `0x010a`, a 22-byte selected RSN
  IE, and Ethernet length 135; M4 Key Info `0x030a`, zero Key Data, zero Key
  Nonce, and Ethernet length 113. In both cases the MIC covers the declared
  EAPOL length with the initially zero MIC field. Hardware capture/association
  is still required to verify the emitted frames on this card.

### TX completion and ACK visibility

- Status upstream: **present**.
- Evidence: the pinned PCI path supports firmware CCX TX reports when
  `IEEE80211_TX_CTL_REQ_TX_STATUS` is set. Without that flag it marks every
  non-`NO_ACK` descriptor completion as ACKed even though descriptor reclaim
  proves DMA consumption, not an over-the-air ACK. The wrapper requested no TX
  reports, marked every management frame `NO_ACK`, and its `txStatus()` callback
  ignored all flags.
- Fix: request real firmware status for unicast management and EAPOL frames,
  retain `NO_ACK` only for multicast/broadcast management, and log ACK/no-ACK
  with authentication, association, action, deauthentication, M2, or M4 frame
  identity. Ordinary data remains off the report path to avoid firmware-report
  overhead and sequence pressure.
- Verification: clean `make all` exited 0. Focused inspection confirms the new
  request flag reaches `rtw_tx_report_enable()`, sets the descriptor's special
  report bit, queues the skb after PCI reclaim, and reaches `txStatus()` only
  after the firmware report supplies the ACK result. Missing reports retain the
  driver's existing explicit timeout warning.

### Required-firmware build guard

- Status upstream: **present**.
- Evidence: the untouched baseline had no `firmware/*.bin`; the generator
  emitted a zero-sentinel-only table and `make all` exited 0. The resulting
  kext could not load the RTL8821CE firmware requested by
  `rtw8821c.c` (`rtw88/rtw8821c_fw.bin`).
- Fix: make `firmware/rtw8821c_fw.bin` an explicit default prerequisite via
  overridable `REQUIRED_FIRMWARE`, and make the generator itself fail when
  invoked on an empty directory. Other chip builds can explicitly override the
  required filename without weakening the empty-table guard.
- Verification: direct generation against the empty tracked firmware directory
  exited 1 with an explicit error. After `make clean`, `make all` exited 2 with
  the missing `firmware/rtw8821c_fw.bin` prerequisite named. A synthetic
  temporary `.bin` outside the repository exercised the non-empty generator
  path and produced one correctly named blob entry; the fixture was removed.
  A successful final kext build requires the user-supplied proprietary firmware
  and cannot be performed from the clean clone alone.

### Embedded-firmware decompression

- Status upstream: **present**.
- Evidence: the generator records both compressed and exact original lengths,
  but the loader ignored `original_size` and allocated `compressed_size * 4`.
  That heuristic is not a valid upper bound for zlib data, so a legitimate blob
  with a compression ratio above 4:1 would fail decompression at boot. The zlib
  allocator also performed its multiplication in the narrow input type and
  used pointer size rather than the actual private-header offset.
- Fix: allocate the exact recorded original length, reject empty or out-of-range
  metadata, require decompression to produce precisely that length, zero the
  `z_stream`, and make the zlib allocator's size calculation overflow-safe.
- Verification: `git diff --check` passed and the changed
  `build/compat/rtw88_firmware.o` target compiled successfully with Apple clang
  16. End-to-end firmware loading remains a hardware test and requires the
  user-supplied `rtw8821c_fw.bin`.

### Association-response use-after-free

- Status upstream: **present**.
- Evidence: `processAssocResponse()` saved a pointer into `skb->data`, called
  `kfree_skb(skb)`, and then read status and AID through that freed pointer.
  It also formed header/body pointers before proving that the frame held the
  fixed header and six-byte response body.
- Fix: validate the complete fixed response first, copy status/AID into local
  values, and only then free the skb. Invalid frames are ignored so the existing
  association timeout remains authoritative.
- Verification: the changed C++ translation unit compiled successfully. Source
  ordering now shows status/AID loads before the sole success-path skb free;
  final linking is firmware-gated.

### BSS/security merging

- Status upstream: **present**.
- Evidence: deduplication by BSSID used a whole-structure `memcpy()`. A later
  beacon/probe response whose RSN IE was absent or unsupported therefore
  replaced previously parsed WPA2 cipher/group/AKM values with zero. A hidden
  SSID observation could similarly erase a known SSID.
- Fix: preserve prior nonzero security metadata when the new observation has no
  parsed cipher, preserve a known SSID across a hidden observation, and retain
  the existing list linkage while updating all other current fields.
- Verification: the changed C++ translation unit compiled successfully.
  Focused merge-path inspection confirms the security/SSID saves occur before
  replacement and are restored only when the new observation lacks them.

### Authentication and management-frame safety

- Status upstream: **partially fixed, with gaps still present**. Upstream had a
  target-BSSID check, but accepted a truncated auth body as success, did not
  validate open-system algorithm/transaction sequence, did not verify receiver
  and source addresses together, and dereferenced RX headers before a fixed
  three-address header length check.
- Fix: reject short RX frames, require target source+BSSID and our receiver
  address for auth/assoc responses, require open-system transaction 2, and
  ignore truncated responses instead of advancing state. The scan fixed-header
  check now uses the actual 24-byte three-address header rather than the larger
  four-address shim structure.
- Verification: the changed C++ translation unit compiled successfully.
  Focused branch inspection confirms no short/auth-address/algorithm/sequence
  failure reaches `doAssociate()`; final linking is firmware-gated.

### Diagnostic instrumentation audit

- Startup/probe stages: `RTW88_STAGE` checkpoints cover wrapper entry, PCI chip
  match, `rtw_pci_probe`, hardware registration, interface creation, driver
  start, and successful completion. They only call `IOLog`; the historical
  1.5-second sleeps were removed, so probe diagnostics cannot themselves alter
  timing or block startup.
- Log retrieval: the compat layer keeps an 8 KiB lock-protected ring in
  addition to `IOLog`. `rtw88ctl log` reads it through the user client, and
  `rtw88ctl debug <0..3>` changes the error/warn/info/debug threshold. The ring
  is drained on read and is therefore observational rather than persistent.
- Scan counters: `_rxFrameCount` is reset at scan start and incremented for each
  accepted RX frame, including manual-scan fallback. Current `scanDone()` does
  not report the value, so this is dead diagnostic state; it is recorded as a
  limitation and was not changed during reconstruction.
- Disconnect diagnostics: accepted AP disassociation and deauthentication
  frames are distinguished by subtype and log their 802.11 reason code. Frames
  failing source/BSSID/receiver validation are dropped without changing link
  state. The TX-status path separately identifies authentication, association,
  action, deauthentication, EAPOL M2, and EAPOL M4 frames.
- Stalled-TX diagnostics: the PCI wrapper polls once per second only while the
  TX path is marked stalled or nearly out of BE descriptors. The dump includes
  hardware/software BE pointers, queue depth, TX DMA/FIFO state, the descriptor
  at the hardware read pointer, RX pointers, and interrupt status/masking bits.
  This is sufficient to distinguish a chip/FIFO stall, DMA descriptor stall,
  missing interrupt, and ring desynchronization without claiming that any one
  cause is proven.
- Interrupt logger: `RTW88IEEE80211::handleInterrupt()` contains ENTER/LEAVE
  logging, but the active PCI interrupt source dispatches directly through
  `rtw88_trigger_interrupt()` and never calls that method. It is therefore
  unreachable in the current PCI path.
- RF watchdog: `rtw88_disable_watchdog_work` remains `true` by default. The
  watchdog reschedules itself but skips Linux rtw88's periodic RF-dynamic and
  Bluetooth-coexistence work, based on the historical observed TX stalls from
  those routines in this macOS bypass. This is an intentional experimental
  stability setting, not evidence that RF adaptation is complete.

The TX report callback is synchronous in this compatibility layer even though
upstream Linux normally queues `ieee80211_tx_status_irqsafe()` work. The current
callback only classifies, logs, and frees the skb; retaining this behavior is a
known lock-context concern for hardware testing, not a claim of Linux-equivalent
interrupt semantics.

### Power-management audit

- Status: **deferred hardware work**.
- `pci_set_power_state()`, `pci_prepare_to_sleep()`, and
  `pci_back_from_sleep()` in the PCI compatibility header are explicit no-ops.
  The PCI wrapper's `powerStateWillChangeTo()` only logs the requested state and
  returns `IOPMAckImplied`; it does not quiesce, suspend, restore, or reinitialize
  the adapter. The user-client power-off path stops the driver, but that is not
  a PCI D3/sleep implementation.
- No speculative sleep/wake implementation was added. Sleep/wake must be tested
  and designed against real macOS power-management callbacks after basic WPA2
  stability is established.

### Remaining scope and licensing audit

- WPA3-SAE, 802.11r/802.11k roaming, MU-MIMO beamforming defaults, SDIO, USB
  throughput tuning, and native macOS Wi-Fi UI integration remain outside this
  reconstruction. The RTL8821CE target is the PCIe path and WPA2-CCMP only;
  control remains through `rtw88ctl` (or the separate Starskiff project).
- USB source and personalities exist in the upstream tree, but
  `RTW88USBDevice.cpp` is excluded from the Makefile because the kext bundle does
  not declare `IOUSBHostFamily`; USB support is not part of this build.
- The EAPOL MIC/PBKDF2/AES code is source-reviewed and the prior session
  observed one complete WPA2 handshake, but no cryptographic or association
  result is being marked verified until this branch is tested on the RTL8821CE.
- No root `LICENSE` file exists. Source headers and `Info.plist` state
  `GPL-2.0 OR BSD-3-Clause`, but redistribution terms remain unconfirmed until
  an actual license file is supplied. Proprietary firmware is not covered by
  that source-header statement and is not committed or redistributed here.

### Whole-branch review concerns

- The single-station registry is intentionally minimal for the port's one-VIF
  model, but its global pointer has no RCU/refcount mechanism. Most Linux lookup
  call sites use `rcu_read_lock()`, while at least the beacon-filter path does
  not; teardown unregisters before freeing but can still race a concurrent
  lookup. This remains a source-level concern to observe before relying on
  repeated connect/disconnect cycles.
- TX-status callbacks are invoked synchronously from compatibility shims where
  upstream Linux uses an IRQ-safe deferred path. The current callback performs
  only bounded frame classification, `IOLog`, and eventual skb free, but lock
  context and log backpressure should be watched during hardware testing.
- The branch intentionally retains existing warnings from the port and vendored
  Linux sources. No unrelated driver feature changes were included.

## First hardware test: association-response panic

The first controlled RTL8821CE test used executable UUID
`FBE36E44-8648-3902-9DE1-07FF65A5D7F3` and SHA-256
`85d10693bc6e200c01e907c5a14eeb96f46501aeab6149642051a9cee7d19ef3`.
OpenCore injection, PCI matching, firmware v24.11 loading, interface creation,
and 2.4/5 GHz scanning succeeded. Connecting to the 5 GHz WPA2 test AP then
panicked in `rtw_bf_assoc()` while processing the association response. This
was before the WPA2 four-way handshake.

### Fault localization

- Panic kext load address: `0xffffff800c549000`; fault RIP:
  `0xffffff800c5766a8`. Their difference is Mach-O text address `0x2d6a8`,
  exactly `rtw_bf_assoc + 360` in the tested executable.
- The instruction at that address is `movl 0x4(%rax), %eax`. The immediately
  preceding code built `%rax` as `sta + 0x98 + 0x18`, which is
  `&sta->deflink.vht_cap`; the four-byte load is therefore
  `vht_cap->cap` in the MU-beamformer capability test.
- The same executable called `_ieee80211_find_sta` and immediately executed
  `cltq` before saving the result. `cltq` sign-extended the low 32-bit value in
  `%eax`, proving that `bf.c` had compiled the function as returning implicit
  `int`, not `struct ieee80211_sta *`.
- The compatibility implementation returned the registered station pointer
  `0xffffffa3e1cfe980`. It also left that pointer in `%rdi`, matching the panic
  register. The caller retained only low 32 bits (`0xe1cfe980`) and sign
  extended them to `0xffffffffe1cfe980`. Adding the `0xb0` VHT-capability
  offset produced panic `%rax = 0xffffffffe1cfea30`; loading its `cap` field at
  `+4` produced `CR2 = 0xffffffffe1cfea34` exactly.

### Object and layout audit

- `src/compat/net/mac80211.h` declared station iteration but did not declare
  either `ieee80211_find_sta()` or `ieee80211_find_sta_by_ifaddr()`. Their
  definitions correctly returned pointers, but the Linux driver call sites
  could not see that type. The Makefile's existing
  `-Wno-implicit-function-declaration` masked the ABI error.
- The station itself was not stale or undersized at this call. It is allocated
  with `IOMallocZero(sizeof(struct ieee80211_sta) + hw->sta_data_size)` and
  registered by its actual pointer only after successful `sta_add`. Measured
  layout is 224 bytes for `ieee80211_sta`, 136 bytes for `rtw_sta_info`, and
  360 bytes total. `deflink` is at `0x98`, `deflink.vht_cap` at `0xb0`, its
  `cap` field at `0xb4`, and `drv_priv` at `0xe0`, all within that allocation.
- The VIF is 208 bytes with an aligned `drv_priv` followed by the measured
  176-byte `rtw_vif`, for the already-correct 384-byte allocation. `rtw_vif`'s
  `bfee` begins at private offset `0x98`; no VIF access caused this fault.
- The 5 GHz `ieee80211_supported_band` is duplicated during hardware
  registration and stored in `hw->wiphy->bands[NL80211_BAND_5GHZ]`. The panic
  executable successfully loaded `ic_vht_cap->cap` through this object
  immediately before faulting on the truncated station-derived pointer. The
  band pointer is therefore not the fault source.
- Compatibility RCU remains a no-op and the single-station registry still has
  the lifetime limitation recorded above, but teardown did not produce this
  address. The valid station pointer survived in `%rdi`; only the caller's
  undeclared-function return conversion corrupted `%rax`.

### Fix and verification

Both station lookup functions now have their exact pointer-returning prototypes
in the public mac80211 compatibility header. This is a structural ABI fix, not
a beamforming bypass or a defensive null check. It also repairs the same return
truncation in the AMPDU, RX-statistics, and firmware beacon-filter call sites.

A forced full rebuild with the supplied `rtw8821c_fw.bin` completed and linked.
A focused `bf.c` compile with implicit declarations promoted to errors also
completed. Disassembly of all four lookup callers now stores the full `%rax`
return directly; none executes `cltq`. The rebuilt kext executable has UUID
`BE2749BA-E392-3807-AF5A-E75A9B772809` and SHA-256
`d2004ad096c0fc68ea1d10be46eddf5d04f769eca673fa96e23cf31d939674a2`.

That executable is the hardware-validated known-good candidate recorded below.

## Hardware-validated known-good candidate

- Path: `build/out/rtw88.kext`, CLI `build/out/rtw88ctl`
- Bundle ID: `com.rtw88.driver` version `1.1.0`, architecture `x86_64`
- Executable SHA-256:
  `d2004ad096c0fc68ea1d10be46eddf5d04f769eca673fa96e23cf31d939674a2`
- Mach-O UUID: `BE2749BA-E392-3807-AF5A-E75A9B772809`
- Firmware input: `firmware/rtw8821c_fw.bin` SHA-256
  `2ef409bc418549fcf294061dd0cae1fc22fd9da79b60524950b25de18732f3f0`
- Runtime firmware version observed on hardware: v24.11
- Association-panic candidate that this replaced:
  SHA-256 `85d10693bc6e200c01e907c5a14eeb96f46501aeab6149642051a9cee7d19ef3`,
  UUID `FBE36E44-8648-3902-9DE1-07FF65A5D7F3`

Testing used a separate experimental USB OpenCore EFI. The internal golden
Ethernet-only EFI was not modified.

### 5 GHz WPA2 (historical test AP)

- SSID: `RTW88_TEST`
- Password: `<test credential omitted>`
- BSSID: `<test-bssid>`
- Channel: 36
- Security: WPA2

Results on the known-good candidate:

- scan PASS
- connect PASS in about 1 second
- previous `rtw_bf_assoc` panic did not recur
- 20-second stability PASS
- DHCP PASS; IPv4 `<test-client-ip>`; gateway `192.168.1.1`
- gateway ping 20/20, 0% loss
- Internet/TLS via `en2` PASS, HTTP 200
- 10 MB download PASS, about 4,084,737 B/s (~32.7 Mbps)
- sustained traffic: 10 × 10 MB transfers, all HTTP 200, ~100 MB total
- concurrent gateway ping during sustained traffic: 60/60, 0% loss
- loaded ping min/avg/max/stddev: 4.224 / 40.817 / 344.716 / 55.639 ms
- disconnect/reconnect PASS
- radio power off/on PASS
- scan after radio cycle PASS
- reconnect after radio cycle PASS
- repeated disconnect/reconnect: 5/5 cycles PASS
- 15/15 gateway pings, 0% loss
- no panic, no random deauth, no stuck interface

The loaded-latency numbers are recorded as observed. They have not been
isolated as a driver bug.

### 2.4 GHz WPA2 (historical test AP)

- SSID: `MERCUSYS_Guest_C35C`
- Password: `<test credential omitted>`
- BSSID: `0a:8a:f1:79:c3:5b`
- Channel: 2
- Security: WPA2

Results on the same known-good candidate:

- scan PASS
- connect PASS in about 1 second
- 20-second stability PASS
- DHCP PASS; IPv4 `<test-client-ip>`
- gateway ping 10/10, 0% loss
- min/avg/max/stddev: 3.019 / 3.892 / 5.430 / 0.645 ms
- 10 MB Internet download PASS, HTTP 200, 1,341,607 B/s (~10.7 Mbps)
- disconnect PASS
- reconnect PASS in about 1 second
- post-reconnect gateway ping 5/5, 0% loss
- no panic, no random deauth, no obvious RX/TX stall

Do not rewrite the historical records above with later SSID renames.

### Current APs for future regression tests

The router SSIDs were changed after the tests above. New hardware tests
must scan first, then use:

- 2.4 GHz: SSID `RTW88_TEST_2.4GHz`, password `<test credential omitted>`,
  router security WPA/WPA2-Personal
- 5 GHz: SSID `RTW88_TEST_5GHz`, password `<test credential omitted>`,
  router security WPA/WPA2-Personal

Before connecting, verify SSID, band/channel, BSSID, and reported security.

## Remaining issues after hardware validation

- RSSI telemetry: source inspection confirmed that RX status is zeroed for
  every non-C2H packet and that packets without PHY status set
  `RX_FLAG_NO_SIGNAL_VAL`, leaving `signal` at zero. The wrapper ignored that
  flag and overwrote both connection and scan RSSI with the meaningless zero.
  It now preserves the last valid connection/BSS value and does not create a
  new BSS entry from a no-signal sample. The Session 1 candidate at commit
  `2ce298904ec87286826865d7766a5d59c9ba9c3e` passed scan, WPA2 connection,
  DHCP/gateway, 10 x 10 MB traffic, and live RSSI sampling with no 0 dBm
  samples, panic, deauthentication, or stall.
- Sleep/wake is still unimplemented and untested. `pci_set_power_state()` and
  related PCI sleep helpers remain no-ops; the PCI wrapper's
  `powerStateWillChangeTo()` only logs. Do not request a sleep test until a
  concrete resume path exists.
- Compatibility RCU is effectively a no-op. The single-station registry may
  lack sufficient locking/refcounting for concurrent teardown.
- Some wider/inactive driver paths still compile with implicit-function-
  declaration warnings suppressed. The association-panic class of ABI bug
  remains a review concern for any still-undeclared pointer-returning calls.
- `rtw88ctl log` was unexpectedly sparse or empty even with debug level 3.

## Current project scope

The remaining work is three sequential phases. Do not expand into the
out-of-scope list below.

Phase 1 — driver hardening: preserve the working 2.4/5 GHz WPA2-Personal
behavior; fix RSSI 0 dBm reporting; audit the active PCI path for implicit
declarations and ABI hazards; audit station registry/lifetime/RCU safety;
make `rtw88ctl` logging useful; implement and validate sleep/wake with
reconnect after wake; then long-duration stability. Controlled performance
analysis only after correctness.

Phase 2 — native-feeling macOS experience: ordinary Wi-Fi use without
Terminal. Target a menu-bar controller with scan, SSID list, current SSID,
signal, 2.4/5 GHz and channel, click-to-connect, password prompt,
disconnect, radio on/off, saved networks, forget/update credentials,
auto-connect after login/boot, auto-reconnect after link loss and wake,
clear user-facing errors, and Keychain storage. `rtw88ctl` remains a
developer/debug tool. Full AirPort/CoreWLAN parity is not required.

Phase 3 — personal Wi-Fi security: Open; WPA2-Personal/PSK; WPA/WPA2 mixed
personal; WPA3-Personal/SAE; WPA2/WPA3 transition mode; PMF as required for
WPA3/transition. Prefer established cryptographic implementations over
custom primitives.

Explicitly out of scope: WPA2/WPA3-Enterprise and 802.1X (PEAP, EAP-TLS,
EAP-TTLS, MSCHAPv2, RADIUS, enterprise certificate UI); AirDrop, Handoff,
AWDL, Continuity; exact Apple AirPort parity; WEP; unrelated USB/SDIO
cleanup unless required for shared correctness.

## Source-review checks

- Before hardware testing, the complete branch diff was reviewed against the
  recorded upstream revision. The remaining station-registry lifetime and
  synchronous TX-status callback issues are recorded above as test concerns.
- `git diff --check` passes, the kext `Info.plist` passes `plutil -lint`, the
  empty-directory firmware generator check fails explicitly as intended, and
  the firmware-independent compatibility, wrapper, driver, and CLI objects
  compile with the host Apple clang toolchain.
- The user subsequently supplied the ignored local
  `firmware/rtw8821c_fw.bin` with SHA-256
  `2ef409bc418549fcf294061dd0cae1fc22fd9da79b60524950b25de18732f3f0`.
  This enabled the forced full build used for the corrected panic candidate.
  No firmware blob or generated proprietary firmware source is committed.

## Session 2: active PCI strict-prototype / ABI audit

Baseline verification on 2026-09-20 matched the hardware-validated Session 1
state exactly: clean branch `reconstruction/rtl8821ce-20260919` at
`2ce298904ec87286826865d7766a5d59c9ba9c3e`, executable SHA-256
`4ba0f5d175c825a741fd95058555c9034301bce486429a1be83659140043c698`,
Mach-O UUID `910FD77B-0C96-3F48-822C-60B16289D09B`, and firmware SHA-256
`2ef409bc418549fcf294061dd0cae1fc22fd9da79b60524950b25de18732f3f0`.

The audited Linux runtime set for RTL8821CE PCI is `main.c`, `mac.c`, `phy.c`,
`fw.c`, `tx.c`, `rx.c`, `sec.c`, `efuse.c`, `coex.c`, `ps.c`, `regd.c`,
`bf.c`, `sar.c`, `util.c`, `pci.c`, `mac80211.c`, `rtw8821c.c`,
`rtw8821c_table.c`, and `rtw8821ce.c`, together with
`src/compat/rtw88_compat.c` and the active PCI/IEEE80211 IOKit wrappers. The
firmware loader/blob and kmod translation units are also linked, but already
compile without the Linux-driver warning suppressions. The Makefile links USB,
SDIO, and other chip-family objects into the monolithic binary, but those are
not reachable through the RTL8821CE PCI probe path.

The normal Linux-driver flags globally suppress implicit-function-declaration,
int-conversion, and incompatible-pointer diagnostics. A new
`make check-active-pci` target compiles the exact active Linux/compat set while
promoting implicit declarations, implicit int, int/pointer conversions,
incompatible pointer/function-pointer types, and return-type mismatches to
errors. USB, SDIO, and unrelated chip families remain outside this scoped
check so their dormant compatibility gaps do not conceal active-path results.

The first strict pass found no additional undeclared pointer-returning helper.
It did find undeclared active compatibility helpers for work scheduling,
restart/BA handling, TX status/depth, cfg80211/regulatory helpers, random MAC
generation, atomic decrement, and timer deletion. Exact declarations matching
their implementations are now public. It also found that several fields in
the compatibility `struct ieee80211_ops` did not match the pinned driver's
callbacks: `conf_tx`, `set_rts_threshold`, `set_bitrate_mask`, `set_antenna`,
and `get_antenna`. Those signatures now match the current rtw88 source. Struct
tags used by callbacks are declared at file scope so C does not create
distinct prototype-scope types. The compatibility diagnostic hook likewise
now has a file-scope `struct rtw_pci` declaration. Explicit casts on the
workqueue completion event preserve the address identity expected by XNU
while making the intentional volatile-qualifier removal visible.

After these fixes, `make check-active-pci` passes all 20 checked translation
units. Disassembly of every checked active object contains no immediate
`callq` followed by `cltq`. In particular, all four station lookup call sites
store the full `%rax` return directly. This rejects recurrence of the exact
implicit-int pointer-truncation sequence that caused the association panic.

Inactive USB core and RTL8821CU pass the same focused diagnostics. Inactive
SDIO does not: both `sdio_align_size()` calls remain undeclared and compile as
`callq _sdio_align_size; cltq`; the compatibility implementation is also an
incorrect `void sdio_align_size(void)` stub. This is a confirmed inactive-path
ABI defect and is deliberately left for any future SDIO-specific work.

A forced `make -B all` completed, the output Info.plist passes `plutil -lint`,
and `git diff --check` passes. The source-only Session 2 candidate has
executable SHA-256
`1853057af5defb70e8b9eb119c984b731de6eeebec495643d6202ecac973ca6b`
and Mach-O UUID `100D6C88-F06D-3FB1-9420-C663C54189DB`. Because the executable
changed, it is not hardware-validated and requires the minimal PCI probe,
scan, WPA2 connect, DHCP/gateway, traffic, disconnect regression before
Session 3.

## Session 3: asynchronous cancellation and teardown

Baseline verification on 2026-09-20 matched the hardware-validated Session 2
state: clean branch `reconstruction/rtl8821ce-20260919` at
`38445849f3a1960c5ccd8d15af12845e5ff05f23`, executable SHA-256
`1853057af5defb70e8b9eb119c984b731de6eeebec495643d6202ecac973ca6b`,
Mach-O UUID `100D6C88-F06D-3FB1-9420-C663C54189DB`, firmware SHA-256
`2ef409bc418549fcf294061dd0cae1fc22fd9da79b60524950b25de18732f3f0`,
and a passing `make check-active-pci`.

### Confirmed old behavior and races

The old workqueue stored only a `pending` bit. Its worker removed the list node
and cleared that bit before invoking the callback. `cancel_work_sync()` merely
cleared the bit: it neither removed a queued node nor waited for a running
callback. A queued callback could therefore run after cancellation and after
its owner was freed. Clearing the bit also allowed the same embedded list node
to be inserted a second time while its first instance remained queued.
`flush_work()` and `flush_workqueue()` polled with fixed sleeps instead of
waiting for state transitions.

Delayed work rebuilt its timer on each schedule, discarded the requested
workqueue, and always dispatched through `system_wq`. Its synchronous cancel
called the ineffective work cancel, so delay expiry could race cancellation
and enqueue work after cancellation returned. Timers tracked `active` without
synchronization. The compatibility implementation of
`thread_call_cancel_wait()` was only `thread_call_cancel()`, a fixed 500-us
`IODelay`, and another cancel; it did not prove that a claimed or executing
callback had exited. IRQ, NAPI, connect, and manual-scan call resources could
therefore be freed while their callback still used the context object.

### Active object and lifecycle inventory

| Owner/object | Callback and scheduling | Required teardown |
|---|---|---|
| `rtwdev->watch_dog_work` | `rtw_watch_dog_work`; core start and self-rearm | synchronous cancel in core stop; self-rearm must be rejected while canceling |
| Eight `rtwdev->coex` delayed works | coexistence callbacks scheduled by `coex.c` | synchronous cancel in core stop and before `rtwdev` free |
| `rtwdev` plain works | `tx`, `c2h`, `ips`, firmware recovery, beacon update, and BA callbacks | drain/cancel after new hardware scheduling is stopped and before PCI/core free |
| `rtw_sta_info::rc_work` | rate-control update | synchronous cancel in `sta_remove` before station free |
| `tx_report.purge_timer` | TX-report timeout purge, armed by TX-report enqueue | synchronous timer deletion in core deinit before `rtwdev` free |
| PCI IRQ and NAPI calls | threaded IRQ and RX poll; NAPI can re-enter itself | interrupts/NAPI stop first, then blocking call destruction before PCI structures are freed |
| `_connectTC`, `_manualScanTC` | authentication and manual scan | blocking cancellation before disconnect/power-off/stop; blocking destruction before C++ owner state is freed |

`rtw_core_stop()` clears the running flags, disables PCI interrupts, stops
NAPI, and then cancels its normal delayed/common work. The wrapper now adds a
final cancel pass for every `rtw_dev` work item, including the work not covered
by core stop, before interface/PCI/core memory is released. The same final
pass runs during radio power-off. Station rate-control work remains canceled
by the driver's existing `sta_remove` ordering.

### Implemented synchronization model

Commit `07d3ca3215570cc8ce6123feaaa113bed1fb4c59` adds explicit idle,
queued, and running work state under one compatibility work lock. Queueing
refuses stopped queues, cancellation in progress, an already-pending item,
cross-queue insertion while running, or a list node that is not self-linked.
A running callback may queue one subsequent instance on the same queue, which
preserves the active driver's self-rearm model without duplicate insertion.

`cancel_work_sync()` now removes a queued instance, blocks callback requeue
while cancellation is active, and condition-waits until any running callback
exits. The worker wakes work and queue waiters on completion. `flush_work()`
and `flush_workqueue()` use the same state notifications; no fixed delay is
used as synchronization. Queue destruction stops admission, drains queued and
running callbacks, waits for its worker to terminate, and only then frees the
queue.

Delayed work records its actual target queue and initializes its timer once.
Publishing delayed state and arming the timer are serialized under the work
lock. Expiry serializes with cancellation before enqueueing. Synchronous
cancel blocks new expiry/rearm, synchronously stops the timer, removes or
waits for underlying work, and returns only when neither delay, queued work,
nor running work remains. This closes both expiry/enqueue and
publish/arm-after-cancel races.

Because XNU's native `thread_call_cancel_wait()` is not KPI-exported, the
compatibility layer now wraps each native call with a lock and explicit
pending/running/canceling state. The wrapper marks execution before invoking
the client and wakes waiters after it exits. Blocking cancellation prevents
new entry, cancels a still-pending native call, and condition-waits for a call
already claimed or running. Destruction keeps entry disabled continuously
through native-call free. Linux timers use this wrapper plus a timer lock;
`del_timer_sync()` blocks callback rearm and does not return until the callback
has exited. No arbitrary sleep or cancel-twice sequence remains.

Commit `41de3fc247eb50674ca91f06dd23fa69c542dc70` converts the active IRQ,
NAPI, connect, and manual-scan paths to the managed calls, waits before freeing
their owners, and quiesces all `rtw_dev` work before final PCI removal or radio
power-off. Manual-scan cancellation also restores a pending scan's state when
the call is canceled before its callback starts.

The final partial-start review found that `stop()` had placed driver stop and
work quiescence inside its `_vif` branch. PCI/core setup followed by a failed
VIF allocation could therefore remove the PCI/core owner without first
stopping its callbacks. Commit
`7c49746957b4e6c15c0161065f728ae17f0862a3` makes driver stop and the final
work-cancel pass independent of VIF existence; VIF removal remains conditional.

Object inspection then caught the C++ users requesting mangled C++ names for
the C implementations. The permissive kext link had left those names as
dynamically looked-up undefined symbols. Commit
`d0912bd3a0b9beba207b9636b77ba3ba53d397bf` gives the managed-call API explicit
C linkage. The rebuilt executable has no undefined `rtw88_thread_call_*` or
`thread_call_cancel_wait` symbol; all managed functions resolve internally.

Exact Linux workqueue concurrency is deliberately not reproduced: every
Feixiao queue has one worker, which is sufficient for this single-driver
active path. Synchronous self-cancel is rejected rather than deadlocked. The
audited active callbacks do not synchronously cancel themselves; watchdog and
NAPI self-rearm use nonblocking queue/entry operations. Reinitializing an
already-live work or timer object and concurrent destruction of the same timer
remain unsupported, and no active call site does either.

### Validation and remaining boundary

A standalone host unit test would require emulating XNU thread calls,
`IOLockSleep`/wakeup, and kernel threads, so it would test the emulator rather
than the compiled kext primitives. Validation instead used locked state-machine
inspection, the duplicate-list invariant, active call-site/lifetime review,
strict compilation, forced and incremental builds, bundle validation, and
symbol inspection. `git diff --check`, `make check-active-pci`, and
`make -B all` pass. The forced build emitted only the repository's previously
known compatibility/upstream warnings; no Session 3 diagnostic was introduced.

The Session 3 executable has SHA-256
`55cacb6e1fe7f0eb562b19cd156c40843d85bce98284273f6d593579ffe0e3eb`
and Mach-O UUID `718ED736-B43C-3587-B528-37B5C9F90FE1`. Its required hardware
regression subsequently passed: exact UUID, initialization, scan, WPA2,
DHCP/gateway traffic, a large HTTP transfer, disconnect/reconnect, radio
off/on, post-cycle scan/reconnect, five reconnect cycles, and final clean
disconnect (56 PASS, 0 FAIL, 0 WARN). This is the current hardware-validated
baseline at `d2b47a096cbb905c2e486fb57928aa2c89b2e069`. Sleep/wake remains out
of scope.

The station registry still stores raw pointers while compatibility RCU is a
no-op. This session ensures callbacks are dead before their owners are freed,
but it deliberately does not redesign station lookup lifetime; that is Session
4 after this candidate passes the required hardware regression.

## Session 3.5: sustained TX rate-adaptation audit

The hardware baseline exposes a directionally asymmetric sustained-transfer
failure on the 5 GHz WPA2 AP: local iperf3 measured 44.8 Mbit/s RX (phone to
Mac) but only 734 Kbit/s TX (Mac to phone), with 16,860 TCP retransmissions and
zero-throughput intervals. Five streams reproduced the asymmetry: 114 Mbit/s
RX versus 2.62 Mbit/s TX and 4,479 retransmissions. Ethernet on the same Mac
was about 90 Mbit/s in both directions, so this is not an ISP/router result.

### Confirmed source defect

The PCI descriptor fill, ring ownership/reclaim, DMA mapping, queue selection,
and firmware TX-report paths are compiled directly from the pinned Linux
`rtw88-stable` revision. Normal data is intentionally not put on the firmware
TX-report queue; upstream marks it ACKed when the PCI completion is reclaimed,
while management and EAPOL frames request and match firmware reports. The
wrapper sends normal unicast data to the BE ring with TID 0, serializes output
through an `IOGatedOutputQueue`, and applies existing BE-ring backpressure.
Those are intentional port adaptations; this review found no demonstrated
descriptor, DMA, report, or reclaim divergence to change.

The association wrapper did have one decisive divergence. It allocated the AP
station itself and copied the *local card's* HT/VHT capability structures from
`wiphy->bands[]` into `sta->deflink`. In Linux, mac80211 supplies that station
with the AP's negotiated capabilities. `rtw_sta_add()` immediately calls
`rtw_update_sta_info()`, which derives the RA mask, rate ID, bandwidth, SGI,
LDPC/STBC, and VHT-enable state from those station fields, then sends the
firmware RA H2C command. In particular, the VHT mask is constructed from the
peer receive-MCS map. Supplying local rather than peer values can therefore
advertise PHY/MCS modes that the AP did not negotiate and cause excessive
over-air retries.

Commit `84ed9f1` adds a bounds-checked decoder for HT and VHT Capability IEs,
uses association-response IEs first, and falls back to the cached beacon/probe
IEs when the response omits them. It installs only those peer values before
`sta_add`; the previously established operating channel width remains the
separate chandef decision. The fix is structural, not a forced-rate,
HT/VHT-disable, ACK, retry, aggregation, or timeout workaround.

This also explains the directionality: the AP receives the card's genuine
capabilities in the association request and selects its downlink rates from
that information, whereas the port had programmed the card's firmware with a
fabricated view of the AP for uplink RA.

The custom BlockAck/AMPDU control path remains a compatibility simplification
and does not implement Linux mac80211 TXQ scheduling. It is not changed here:
the code has no evidence that it is the source of the measured failure. The
next hardware run must verify that the corrected RA input resolves the
sustained-TX symptom before any further performance changes are considered.

### Source validation and candidate status

`git diff --check` passed before commit. A forced `make -B all` passed; the
only diagnostics were the pre-existing compatibility warnings. The focused
active PCI strict check and ordinary incremental build both pass. The kext
Info.plist passes `plutil -lint` and the executable is a 64-bit x86_64 Mach-O.
The source-built candidate at `84ed9f1` has executable SHA-256
`511c833dc618b69ced95895645fd44562f3eef1c2b823c61c057f3c0e54ec051`
and Mach-O UUID `55AB9A60-F92B-3A0A-80B0-28A1A29AC465`. It is **not
hardware-validated**. The latest hardware-validated baseline remains
`d2b47a096cbb905c2e486fb57928aa2c89b2e069`.

### Hardware result: peer-capability correction was insufficient

The `20b10f8` candidate was booted fresh and its exact UUID was verified.
On `<5GHz-test-ssid>` (channel 36, WPA2, RSSI about -26 to -30 dBm), association and
DHCP succeeded, but reverse local iperf3 (Mac to phone) delivered only
803 Kbit/s over 30 seconds with 30,204 TCP retransmissions. Traffic initially
reached 1–6 Mbit/s, then collapsed after roughly 10–16 seconds into repeated
zero-throughput intervals and a 2.83-KByte congestion window. The RX control
remained stable at 44.9 Mbit/s. This proves the peer-capability defect is real
but not sufficient to explain the sustained-TX failure; `20b10f8` is not
hardware-validated and the validated baseline remains `d2b47a0`.

### Next diagnostic candidate

Commit `35ee688` adds no descriptor/rate/AMPDU/security behavior change. It
adds atomic aggregate diagnostics only: data submitted/completed bytes and
frames, AMPDU/non-AMPDU and encrypted counts, report outcomes, DMA
map/failure/unmap counts, interrupt bottom halves, output stall/resume counts,
the last data sequence and CCMP packet number (never key material), and the
RA mask/rate ID/bandwidth/VHT/SGI snapshot captured after station add. During
active TX the existing one-second timer emits one `TXDIAG` line and one BE-ring
snapshot, containing hardware/software producer-consumer indices, queue
length, free slots, descriptor contents at the hardware read pointer, and DMA
active/pending-free counts. It does not log per packet.

Its executable SHA-256 is
`060ca0a6e500139129ce56f2b57dedd422ba23a2e64f74177a4a5b571193226e` and
its Mach-O UUID is `B6864B95-FD56-3EA5-B6AC-CA2A11636A3F`.

The next controlled reverse iperf3 run must preserve the `TXDIAG` and
`TXSTATE` lines from connect through failure. They distinguish un-reclaimed
descriptors, missing interrupt completion, ring-full backpressure, DMA
accumulation/mapping failures, sequence/PN discontinuity, BA use, and firmware
RA configuration before any speculative functional change is made.

### Hardware result: timer diagnostics were not observable

The diagnostic kext at `59ad63e` (Mach-O UUID
`B6864B95-FD56-3EA5-B6AC-CA2A11636A3F`) reproduced the failure twice. The
30-second Mac-to-phone results were 768 Kbit/s with 6,991 TCP retransmissions
and 733 Kbit/s with 7,020 retransmissions. Both runs made limited progress for
roughly ten seconds and then spent long intervals at zero throughput, while
the phone-to-Mac RX controls remained stable at 44.8 and 44.6 Mbit/s.

No `TXDIAG` or `TXSTATE` line reached `dmesg`, although their strings and
counter updates are present in the loaded executable. Both emissions depended
on `RTW88PCIDevice::debugTimerFired()`, so the hardware result cannot
distinguish a stopped/unrearmed `IOTimerEventSource` from that callback being
blocked before its logging statements. The targeted diagnostic below does not
depend on that timer.

The second run did produce 46 instances of `pci bus timeout, check dma
status`, approximately 100 ms apart. Source comparison with pinned Linux
commit `d029a677c49266fad86750714eb5612becd134d3` proves that this wording is
misleading: `rtw_pci_dma_check()` compares the expected 13-bit
`rtwpci->rx_tag` with the observed RX descriptor `total_pkt_size` tag before
advancing the expected tag modulo `RX_TAG_MAX` (8192). The active code and
reference are identical in this path. The warning is evidence of RX tag
mismatch, not a TX-DMA timeout, and the correlation alone does not establish
whether it contributes to the TX failure.

### TARGETED SESSION 3.5 DIAGNOSTIC CANDIDATE — NOT HARDWARE VALIDATED

Sibling-driver commit `63ad004` replaces the generic warning on macOS with a
direct, once-per-second `TXRXDIAG` snapshot. The mismatch branch calls
`rtw_pci_diag_rx_tag_mismatch()` synchronously; that helper calls `rtw_warn()`,
which reaches the existing `rtw88_dev_printk()`/`IOLog()` path already proven
visible in `dmesg`. There is no timer, workqueue, or deferred logging stage.
The mismatch count itself is cumulative even when rate-limited samples are
suppressed.

Each sample records the RX descriptor index, expected/observed tags, modular
and shortest signed delta, cumulative mismatch count, current expected tag,
raw RXBD index register, and decoded RX hardware/software indices. Under the
PCI IRQ lock it also snapshots the BE TXBD register, hardware write/read and
software write/reclaim indices, ring length/occupancy/availability, skb queue
length, the two buffer-descriptor DMA addresses and lengths at the hardware
read index, PSB field, TXDMA status, HISR0, conditional HISR3, and BEDOK state.
The third line includes cumulative and interval data submissions/completions,
bytes, outstanding frames, exact BE completion-interrupt and overall interrupt
bottom-half counts, AMPDU/non-AMPDU/encrypted counts, firmware-report
status/ACK/failure totals, DMA maps/failures/unmaps/active count, output
stall/resume/current state, and the already-cached RA mask, rate ID, bandwidth,
VHT, and SGI state. Main-tree commit `69a2dec` supplies only the current
output-stall field used by this snapshot.

Ordinary BE descriptors on this hardware have no ownership/completion bit;
completion is represented by advancement of the TX queue hardware read
pointer, so the log explicitly prints `own=NA`. HISR3 is read only on chips
with the 3081 WCPU register layout and is therefore zero/not applicable for
RTL8821CE. The diagnostic deliberately does not traverse the pending-free or
active-DMA linked lists; `dma_maps - dma_unmaps` supplies the cheap aggregate
instead. It changes no RX wait/resynchronization behavior, rate control,
aggregation, retry, descriptor, or queue semantics.

Static inspection and disassembly confirm the direct mismatch-to-helper and
helper-to-`rtw88_dev_printk()` calls. `git diff --check`, the 20-unit
`make check-active-pci`, and forced/incremental builds pass. The Info.plist is
valid and the executable is x86_64. The resulting executable SHA-256 is
`c094c6b2e58465d0dd13abcf2dcac474cb4230d9190f71fc983514ef17c495d0`
and its Mach-O UUID is `D9120075-366E-351B-9B4C-7EC4DAAE6B36`.

The latest hardware-validated baseline remains
`d2b47a096cbb905c2e486fb57928aa2c89b2e069`. This candidate requires one
controlled 30-second reverse local iperf3 reproduction with complete
`TXRXDIAG` lines preserved before the TX failure mechanism can be classified
or a functional fix justified.

### Recovered targeted-log result

Timestamp-based recovery of the kernel ring found 246 new matching rtw88
lines. The earlier zero-line result was an artifact of comparing append-style
snapshots of a ring buffer. Both `TXRXDIAG` and timer-driven `TXDIAG`/`TXSTATE`
were present, so neither logging implementation is globally nonfunctional.

The captured direct samples were from the subsequent phone-to-Mac RX control,
not the failing Mac-to-phone reverse test. The proof is the submission
profile: one representative interval submitted 715 frames and 67,210 bytes,
exactly 94 bytes per frame, consistent with outbound TCP ACKs during the
stable 44.7-Mbit/s receive stream. Consequently, these samples cannot be used
to characterize the BE ring during the reverse-TX collapse.

They do prove that the ring, DMA, and output queue made healthy progress under
that RX-control workload. Register/software indices remained aligned or only
one descriptor apart, availability stayed about 97--159 descriptors, TXDMA
status stayed zero, and submission and completion totals advanced together.
Every sample satisfied `active DMA mappings - outstanding TX = 1025`; after
TX drained, those values were 1025 and zero. The fixed 1025 baseline therefore
accounts for RX/static mappings, while incremental active mappings exactly
tracked outstanding TX. DMA mapping failures remained zero. Output stall and
resume counts were balanced after drain, with a one-count difference only
while the current stalled flag was set.

The RX-tag mismatch is a persistent sequence desynchronization, not a brief
descriptor-visibility delay. For about 24 seconds the observed tag remained
three behind the expected tag, then slipped two more positions and remained
five behind, including after the BE TX ring was completely empty. Stable
44.7-Mbit/s RX coexisted with that offset. This does not prove that RX-tag
desynchronization causes the sustained uplink failure, and the reverted RX
polling patch remains inappropriate without separate evidence.

The timer diagnostics had no useful samples from the actual failing reverse
TX interval. Whether the timer was delayed, starved, or blocked specifically
during bulk outbound TX remains unproven; subsequent diagnosis does not rely
on it.

### SESSION 3.5 TX-PATH DIAGNOSTIC CANDIDATE — NOT HARDWARE VALIDATED

Pinned-driver commit `1721c75` adds a separate `TXPATHDIAG` sampler directly
to normal BE transmission. `rtw_pci_tx_write_data()` copies the exact buffer
descriptor index, DMA fields, lengths, PSB, and original 802.11 frame length
after descriptor preparation and calls the helper synchronously after the
descriptor has been queued and `irq_lock` released. This occurs immediately
before the existing `rtw_tx()` doorbell/kick step. It is independent of RX,
NAPI, timers, and workqueues.

The same once-per-second gate permits a fallback `reason=reclaim` sample from
the threaded BE-DOK path when no submit sample has occurred for at least one
second. The call occurs only after `rtw_pci_tx_isr()` has reclaimed completed
frames and the interrupt thread has released `irq_lock`. Submit and reclaim
therefore share one rate limiter and can emit at most one four-line sample per
second. Logging still uses `rtw_warn()` through the proven
`rtw88_dev_printk()`/`IOLog()` path.

Each sample reports reason, submitted frame length, queue and descriptor,
descriptor DMA/length/PSB fields, raw BE TXBD, register and software indices,
ring occupancy/availability/queue length/queue-stopped state, TXDMA status,
HISR0/applicable HISR3/BEDOK, BE-DOK and overall bottom-half counts, aggregate
and interval submissions/completions, outstanding frames, AMPDU/non-AMPDU and
encryption totals, report outcomes, DMA accounting, output-stall state, and
cached RA state. It performs no list traversal and changes no descriptor,
queue, reclaim, RX-tag, rate, aggregation, retry, or encryption behavior.

`make check-active-pci` passes all 20 active units. A forced build passes with
the pre-existing warning set, the Info.plist is valid, and the executable is
x86_64. Object disassembly contains direct calls to the helper from both
`rtw_pci_tx_write_data()` (`submit`) and
`rtw_pci_interrupt_threadfn()` (`reclaim`). The resulting executable SHA-256
is `5876038c4c0b0485316bcaf03cd4186b58ea5dab8ecbf8da221faff0259a9732`
and its Mach-O UUID is `F34202C9-EA4E-393D-B4E7-5BD377474F9E`.

The hardware-validated baseline remains
`d2b47a096cbb905c2e486fb57928aa2c89b2e069`. The new candidate requires a
reverse-only 30-second local iperf3 run with timestamped `TXPATHDIAG` capture
covering setup, the initial progress interval, collapse, and post-test drain.

## Final project state — archived September 2026

The direct TX-path diagnostic candidate was subsequently hardware-tested. A
30-second single-stream local Mac-to-peer iperf3 run reproduced the sustained
TX failure at approximately 733 Kbit/s with 7,020 TCP retransmissions. Direct
`TXPATHDIAG` capture showed that 1542-byte BE data descriptors continued to be
submitted and reclaimed while TCP throughput collapsed.

The PCI TX path did **not** exhibit a sustained stall: the hardware read
pointer and software reclaim pointer advanced, the ring retained substantial
free space, `qstop` remained clear, `TXDMA_STATUS` stayed zero, and DMA mapping
failures remained zero. When TCP stopped feeding new data, the outstanding TX
ring drained normally. DMA accounting also remained consistent with a fixed
1025-mapping RX/static baseline plus the number of outstanding TX mappings.

This localizes the unresolved failure above PCI/DMA submission and below TCP,
in the over-air 802.11/firmware TX behavior. Static comparison against pinned
Linux rtw88 identified the simplified custom TX Block Ack/A-MPDU state machine
as the strongest remaining hypothesis: the port uses a minimal boolean BA
state and does not reproduce mac80211's full per-TID pending/operational,
negotiated-window, timeout, BAR, and recovery semantics. Nearly all bulk data
was being AMPDU-marked. No concrete CCMP packet-number, sequence-number,
firmware-RA, retry-register, or PCI descriptor defect was proven.

The next planned experiment was a single-variable non-A-MPDU build: preserve
QoS TID 0, CCMP, sequence/PN handling, firmware RA, channel width, queueing and
PCI behavior, while suppressing TX ADDBA and `IEEE80211_TX_CTL_AMPDU`. That
candidate was **not built or tested** before the project was discontinued.

Final source snapshot references:

- Feixiao source HEAD: `cf94a13eb5315baba577319f0c7a181ed5d99760`
- rtw88-stable source HEAD: `1721c751ee7e7b1c38ae187cc703b20ac3e3ca85`
- pinned Linux reference baseline: `d029a677c49266fad86750714eb5612becd134d3`
- last fully hardware-validated functional baseline: `d2b47a096cbb905c2e486fb57928aa2c89b2e069`
- final diagnostic kext SHA-256: `5876038c4c0b0485316bcaf03cd4186b58ea5dab8ecbf8da221faff0259a9732`
- final diagnostic kext Mach-O UUID: `F34202C9-EA4E-393D-B4E7-5BD377474F9E`

The project is archived in an unfinished experimental state and should not be
presented as a production-ready macOS Wi-Fi driver.
