#!/bin/zsh

set -u
setopt PIPE_FAIL

SCRIPT_DIR="${0:A:h}"
RTW="${RTW:-$SCRIPT_DIR/../Feixiao/build/out/rtw88ctl}"

SSID="${RTW_TEST_SSID:-RTW88_TEST_5GHz}"
PASSWORD="${RTW_TEST_PASSWORD:-}"
: "${PASSWORD:?Set RTW_TEST_PASSWORD before running this test}"
IFACE="en2"

EXPECTED_UUID="100D6C88-F06D-3FB1-9420-C663C54189DB"
EXPECTED_BSSID="${RTW_TEST_BSSID:-}"
: "${EXPECTED_BSSID:?Set RTW_TEST_BSSID before running this test}"

LOG="$HOME/Desktop/rtw88-session2-fixed-$(date +%Y%m%d-%H%M%S).log"

exec > >(tee "$LOG") 2>&1

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

pass() {
    echo "PASS: $*"
    (( PASS_COUNT++ ))
}

fail() {
    echo "FAIL: $*"
    (( FAIL_COUNT++ ))
}

warn() {
    echo "WARN: $*"
    (( WARN_COUNT++ ))
}

section() {
    echo
    echo "================================================================"
    echo "$*"
    echo "================================================================"
}

get_status() {
    "$RTW" status 2>&1
}

section "SESSION 2 HARDWARE REGRESSION — CORRECTED"

echo "Date: $(date)"
echo "Log:  $LOG"

section "1. VERIFY LOADED KEXT"

LOADED="$(kmutil showloaded 2>/dev/null | grep 'com\.rtw88\.driver' || true)"
echo "$LOADED"

if [[ -z "$LOADED" ]]; then
    fail "rtw88 kext not loaded"
    exit 1
fi

pass "rtw88 kext loaded"

if echo "$LOADED" | grep -q "$EXPECTED_UUID"; then
    pass "Session 2 UUID confirmed"
else
    fail "wrong kext UUID"
    exit 1
fi

section "2. INITIAL DRIVER STATUS"

OUT="$(get_status)"
echo "$OUT"

if echo "$OUT" | grep -q 'Card:.*RTL8821CE'; then
    pass "RTL8821CE initialized"
else
    fail "RTL8821CE initialization missing"
    exit 1
fi

section "3. DISCONNECT BEFORE SCAN"

if echo "$OUT" | grep -q '^State:.*connected'; then
    "$RTW" disconnect || true
    sleep 2
fi

section "4. SCAN"

if "$RTW" scan -w 10; then
    pass "scan completed"
else
    fail "scan failed"
    exit 1
fi

LIST="$("$RTW" list 2>&1)"
echo
echo "$LIST"

TARGET="$(echo "$LIST" | grep -F "$SSID" | head -1)"

if [[ -z "$TARGET" ]]; then
    fail "$SSID not found"
    exit 1
fi

echo
echo "Target:"
echo "$TARGET"

pass "$SSID found"

if echo "$TARGET" | grep -Fq "$EXPECTED_BSSID"; then
    pass "expected BSSID confirmed"
else
    fail "BSSID mismatch"
fi

if echo "$TARGET" | grep -Eq '[[:space:]]36[[:space:]]+WPA2'; then
    pass "channel 36 / WPA2 confirmed"
else
    fail "channel/security mismatch"
fi

SCAN_RSSI="$(echo "$TARGET" | grep -oE -- '-[0-9]+ dBm' | head -1)"

if [[ -n "$SCAN_RSSI" ]]; then
    pass "scan RSSI plausible: $SCAN_RSSI"
else
    fail "scan RSSI invalid"
fi

section "5. CONNECT"

"$RTW" connect "$SSID" "$PASSWORD"

CONNECTED=0

for i in {1..15}; do
    OUT="$(get_status)"
    STATE="$(echo "$OUT" | awk '/^State:/ {print $2; exit}')"

    echo "[$i/15] state=$STATE"

    if [[ "$STATE" == "connected" ]]; then
        CONNECTED=1
        break
    fi

    sleep 1
done

if (( CONNECTED )); then
    pass "WPA2 connected"
else
    fail "connection failed"
    exit 1
fi

echo "$OUT"

section "6. WAIT FOR REAL DHCP"

IP=""

for i in {1..30}; do
    CANDIDATE="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

    if [[ -n "$CANDIDATE" && "$CANDIDATE" != 169.254.* ]]; then
        IP="$CANDIDATE"
        echo "[$i/30] IPv4=$IP"
        break
    fi

    if [[ -n "$CANDIDATE" ]]; then
        echo "[$i/30] waiting for DHCP; current link-local=$CANDIDATE"
    else
        echo "[$i/30] waiting for IPv4..."
    fi

    sleep 1
done

if [[ -z "$IP" ]]; then
    fail "no non-link-local DHCP address after 30 seconds"
    exit 1
fi

pass "real IPv4 acquired: $IP"

DHCP="$(ipconfig getpacket "$IFACE" 2>/dev/null || true)"

echo
echo "$DHCP"

GATEWAY="$(
    echo "$DHCP" |
    awk '
        /router \(ip_mult\)/ {
            if (match($0, /[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/)) {
                print substr($0, RSTART, RLENGTH)
                exit
            }
        }
    '
)"

if [[ -n "$GATEWAY" ]]; then
    pass "DHCP gateway acquired: $GATEWAY"
else
    GATEWAY="$(route -n get default 2>/dev/null | awk '/gateway:/ {print $2; exit}')"
fi

if [[ -z "$GATEWAY" ]]; then
    fail "no gateway available"
    exit 1
fi

echo "Gateway: $GATEWAY"

section "7. GATEWAY TEST"

if ping -S "$IP" -c 10 "$GATEWAY"; then
    pass "gateway ping passed"
else
    fail "gateway ping failed"
    exit 1
fi

section "8. INTERNET TRANSFER"

URLS=(
    'https://speed.cloudflare.com/__down?bytes=10000000'
    'https://proof.ovh.net/files/10Mb.dat'
    'https://speed.hetzner.de/10MB.bin'
)

TRANSFER_OK=0

for URL in "${URLS[@]}"; do

    echo
    echo "Trying: $URL"

    RESULT="$(
        curl \
            --interface "$IFACE" \
            -4 \
            -L \
            --connect-timeout 10 \
            --max-time 90 \
            -sS \
            -o /dev/null \
            -w '%{size_download}|%{speed_download}|%{time_total}|%{http_code}' \
            "$URL"
    )"

    RC=$?

    SIZE="$(echo "$RESULT" | cut -d'|' -f1)"
    SPEED="$(echo "$RESULT" | cut -d'|' -f2)"
    TIME="$(echo "$RESULT" | cut -d'|' -f3)"
    HTTP="$(echo "$RESULT" | cut -d'|' -f4)"

    echo "Downloaded: $SIZE bytes"
    echo "Speed:      $SPEED B/s"
    echo "Time:       $TIME s"
    echo "HTTP:       $HTTP"

    if (( RC == 0 )) &&
       [[ "$HTTP" == "200" ]] &&
       (( SIZE >= 9000000 )); then

        TRANSFER_OK=1
        pass "large HTTP transfer succeeded"
        break
    fi

    warn "endpoint failed; trying next source"
done

if (( ! TRANSFER_OK )); then
    fail "all large-transfer endpoints failed"
fi

section "9. POST-TRAFFIC STATUS"

OUT="$(get_status)"
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*connected'; then
    pass "connection remained connected"
else
    fail "connection dropped"
fi

RSSI="$(echo "$OUT" | awk '/^RSSI:/ {print $2; exit}')"

if [[ "$RSSI" == -* ]]; then
    pass "RSSI remains plausible: ${RSSI} dBm"
else
    fail "RSSI invalid"
fi

section "10. FINAL GATEWAY TEST"

IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if [[ -n "$IP" && "$IP" != 169.254.* ]] &&
   ping -S "$IP" -c 5 "$GATEWAY"; then
    pass "final gateway test passed"
else
    fail "final gateway test failed"
fi

section "11. DISCONNECT"

"$RTW" disconnect
sleep 2

OUT="$(get_status)"
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*idle'; then
    pass "clean disconnect / idle"
else
    fail "driver did not return to idle"
fi

section "SUMMARY"

echo "PASS checks: $PASS_COUNT"
echo "FAIL checks: $FAIL_COUNT"
echo "WARN checks: $WARN_COUNT"

echo
echo "Log:"
echo "$LOG"

if (( FAIL_COUNT == 0 )); then
    echo
    echo "================================================================"
    echo "OVERALL RESULT: PASS"
    echo "Session 2 hardware gate PASSED."
    echo "================================================================"
    exit 0
else
    echo
    echo "================================================================"
    echo "OVERALL RESULT: FAIL"
    echo "Do not start Session 3."
    echo "================================================================"
    exit 1
fi
