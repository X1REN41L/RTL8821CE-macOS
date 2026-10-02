#!/bin/bash
# RTL88WiFi compatibility check (read-only).
#
#   bash tools/rtl88wifi-check.sh            # before or after installing
#   bash tools/rtl88wifi-check.sh --speed    # also run ping + networkQuality
#
# Prints a checklist and a report block to paste into a compatibility issue.
# Changes nothing on the system. The report leaves out MAC addresses, IP
# addresses and network names.

set -u
SPEED=0
[ "${1:-}" = "--speed" ] && SPEED=1

PASS=0; WARN=0; FAIL=0
ok()   { printf '  [ OK ] %s\n' "$1"; PASS=$((PASS+1)); }
warn() { printf '  [WARN] %s\n' "$1"; WARN=$((WARN+1)); }
bad()  { printf '  [FAIL] %s\n' "$1"; FAIL=$((FAIL+1)); }

chip_name() {
    case "$1" in
        c821|b821) echo "RTL8821CE" ;;
        b822)      echo "RTL8822BE" ;;
        c822|c82f) echo "RTL8822CE" ;;
        *)         echo "" ;;
    esac
}

# ioreg prints IDs as little-endian bytes: <21c80000> -> c821.
le16() { local h="${1//[<>]/}"; echo "${h:2:2}${h:0:2}"; }

echo "RTL88WiFi compatibility check"
echo

# --- System -----------------------------------------------------------------
OSVER=$(sw_vers -productVersion 2>/dev/null)
OSBUILD=$(sw_vers -buildVersion 2>/dev/null)
KERNEL=$(uname -r)
MODEL=$(sysctl -n hw.model 2>/dev/null)
CPU=$(sysctl -n machdep.cpu.brand_string 2>/dev/null)
SIP=$(csrutil status 2>/dev/null | sed -n 's/.*status: //p' | tr -d '.')
echo "System"
KMAJ=${KERNEL%%.*}
if [ "$KMAJ" -ge 23 ] 2>/dev/null; then
    ok "macOS $OSVER ($OSBUILD), kernel $KERNEL: Sonoma or later, full setup applies"
elif [ "$KMAJ" -eq 22 ] 2>/dev/null; then
    warn "macOS $OSVER ($OSBUILD): Ventura, untested (see README, Ventura row)"
else
    bad "macOS $OSVER ($OSBUILD): older than Ventura, not supported"
fi
echo "         SMBIOS $MODEL, $CPU, SIP $SIP"
echo

# --- Wi-Fi chip -------------------------------------------------------------
echo "Wi-Fi chip"
CHIPS=""; OTHER=""
while read -r ven dev; do
    [ "$ven" = "10ec" ] || continue
    name=$(chip_name "$dev")
    if [ -n "$name" ]; then CHIPS="$CHIPS $name(10ec:$dev)"; else OTHER="$OTHER 10ec:$dev"; fi
done < <(ioreg -r -c IOPCIDevice -l -w0 | awk '
    /\+-o/ { if (v != "" && d != "") print v, d; v=""; d="" }
    /"vendor-id" = </ { v=$NF }
    /"device-id" = </ { d=$NF }
    END { if (v != "" && d != "") print v, d }' |
    while read -r v d; do echo "$(le16 "$v") $(le16 "$d")"; done)
CHIPS=${CHIPS# }
if [ -n "$CHIPS" ]; then
    case "$CHIPS" in
        *RTL8821CE*) ok "Found $CHIPS: tested chip" ;;
        *)           warn "Found $CHIPS: matched by the kext, not yet confirmed on hardware; please report" ;;
    esac
else
    bad "No supported Realtek Wi-Fi chip (RTL8821CE/8822BE/8822CE, PCIe) found"
fi
[ -n "$OTHER" ] && echo "         Other Realtek PCI devices (not Wi-Fi targets, e.g. Ethernet):$OTHER"
echo

# --- Kexts ------------------------------------------------------------------
echo "Kexts"
LOADED=$(kmutil showloaded 2>/dev/null || kextstat 2>/dev/null)
for id in io.github.x1ren41l.RTL88WiFi com.apple.iokit.IO80211FamilyLegacy com.apple.iokit.IOSkywalkFamily; do
    line=$(echo "$LOADED" | grep -F " $id " | head -1)
    if [ -n "$line" ]; then
        ver=$(echo "$line" | sed -n 's/.*'"$id"' (\([^)]*\)).*/\1/p')
        ok "$id ($ver) loaded"
    else
        bad "$id not loaded"
    fi
done
if echo "$LOADED" | grep -qiE 'AMFIPass'; then ok "AMFIPass loaded"
elif [ "$KMAJ" -ge 23 ] 2>/dev/null; then warn "AMFIPass not seen in the loaded list (needed on Sonoma and later)"; fi
if echo "$LOADED" | grep -qiE 'itlwm|AirportItlwm|com\.rtw88\.airport|AirPortBrcm'; then
    bad "Another Wi-Fi driver is loaded; enable only one Wi-Fi driver"
fi
DRIVERBUILD=$(ioreg -r -c RTL88WiFi -l -w0 2>/dev/null | sed -n 's/.*"DriverBuild" = "\([^"]*\)".*/\1/p' | head -1)
[ -n "$DRIVERBUILD" ] && echo "         DriverBuild $DRIVERBUILD"
echo

# --- Link -------------------------------------------------------------------
echo "Link"
IF=$(ioreg -r -c RTL88WiFiInterface -l -w0 2>/dev/null | sed -n 's/.*"BSD Name" = "\([^"]*\)".*/\1/p' | head -1)
RSSI=""; CHAN=""; LINK=""
if [ -z "$IF" ]; then
    bad "No RTL88WiFi network interface"
else
    LINK=$(ifconfig "$IF" 2>/dev/null | sed -n 's/.*status: //p')
    RSSI=$(ioreg -r -c RTL88WiFi -l -w0 | sed -n 's/.*"RADIO_RSSI" = "\([^"]*\)".*/\1/p' | head -1)
    CHAN=$(ioreg -r -c RTL88WiFi -l -w0 | sed -n 's/.*"RADIO_CHANNEL" = \([0-9]*\).*/\1/p' | head -1)
    if [ "$LINK" = "active" ]; then
        ok "Interface $IF active, channel ${CHAN:-?}, signal ${RSSI:-?}"
    else
        warn "Interface $IF present but not connected (status: ${LINK:-unknown}); join a network and run again"
    fi
    if ifconfig "$IF" 2>/dev/null | grep -q 'inet '; then ok "IPv4 address assigned"; else warn "No IPv4 address on $IF"; fi
    if route -n get default 2>/dev/null | grep -q "interface: $IF"; then ok "Default route uses $IF"
    else warn "Default route is not on $IF (another interface may be preferred)"; fi
fi
echo

# --- Optional speed test ----------------------------------------------------
PINGRES=""; NQRES=""
if [ "$SPEED" = 1 ] && [ "$LINK" = "active" ]; then
    echo "Speed (about 1 minute)"
    GW=$(route -n get default 2>/dev/null | sed -n 's/.*gateway: //p')
    if [ -n "$GW" ]; then
        PINGRES=$(ping -c 50 -i 0.2 "$GW" 2>/dev/null | tail -2 | tr '\n' ' ')
        echo "         router ping: $PINGRES"
    fi
    if command -v networkQuality >/dev/null; then
        NQRES=$(networkQuality -s -I "$IF" 2>/dev/null | grep -E 'capacity|Responsiveness|Idle' | sed 's/^ *//' | tr '\n' ';')
        echo "         networkQuality: $NQRES"
    fi
    echo
fi

# --- Summary and report -----------------------------------------------------
echo "Result: $PASS ok, $WARN warnings, $FAIL failures"
if [ "$FAIL" -eq 0 ] && [ "$LINK" = "active" ]; then
    echo "RTL88WiFi is working on this machine."
elif [ -z "$DRIVERBUILD" ] && [ -n "$CHIPS" ]; then
    echo "Chip and macOS look suitable. Follow the README setup guide, reboot, and run this again."
fi
echo
echo "---- copy from here into your compatibility report ----"
cat <<EOF
- Chip: ${CHIPS:-none found}
- macOS: $OSVER ($OSBUILD), kernel $KERNEL
- SMBIOS / CPU: $MODEL / $CPU
- SIP: $SIP
- DriverBuild: ${DRIVERBUILD:-not loaded}
- Link: ${LINK:-n/a}, channel ${CHAN:-?}, signal ${RSSI:-?}
- Router ping: ${PINGRES:-not run}
- networkQuality: ${NQRES:-not run}
- Check result: $PASS ok / $WARN warn / $FAIL fail
EOF
echo "---- end ----"
[ "$FAIL" -eq 0 ]
