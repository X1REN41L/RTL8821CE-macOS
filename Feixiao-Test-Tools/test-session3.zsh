#!/bin/zsh

set -u
setopt PIPE_FAIL

SCRIPT_DIR="${0:A:h}"
RTW="${RTW:-$SCRIPT_DIR/../Feixiao/build/out/rtw88ctl}"

SSID="${RTW_TEST_SSID:-RTW88_TEST_5GHz}"
PASSWORD="${RTW_TEST_PASSWORD:-}"
: "${PASSWORD:?Set RTW_TEST_PASSWORD before running this test}"
IFACE="en2"

EXPECTED_UUID="718ED736-B43C-3587-B528-37B5C9F90FE1"
EXPECTED_BSSID="${RTW_TEST_BSSID:-}"
: "${EXPECTED_BSSID:?Set RTW_TEST_BSSID before running this test}"

LOG="$HOME/Desktop/rtw88-session3-$(date +%Y%m%d-%H%M%S).log"

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

driver_status() {
    "$RTW" status 2>&1
}

wait_connected() {
    local i out state

    for i in {1..15}; do
        out="$(driver_status)"
        state="$(echo "$out" | awk '/^State:/ {print $2; exit}')"

        echo "[$i/15] state=$state"

        if [[ "$state" == "connected" ]]; then
            return 0
        fi

        sleep 1
    done

    return 1
}

wait_real_ip() {
    local i candidate

    for i in {1..30}; do
        candidate="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

        if [[ -n "$candidate" && "$candidate" != 169.254.* ]]; then
            echo "$candidate"
            return 0
        fi

        if [[ -n "$candidate" ]]; then
            echo "[$i/30] waiting for DHCP; current=$candidate" >&2
        else
            echo "[$i/30] waiting for DHCP..." >&2
        fi

        sleep 1
    done

    return 1
}

get_gateway() {
    ipconfig getpacket "$IFACE" 2>/dev/null |
    awk '
        /router \(ip_mult\)/ {
            if (match($0, /[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+/)) {
                print substr($0, RSTART, RLENGTH)
                exit
            }
        }
    '
}

connect_and_wait() {
    local ip

    "$RTW" connect "$SSID" "$PASSWORD" || return 1
    wait_connected || return 1

    ip="$(wait_real_ip)" || return 1

    echo "IPv4: $ip"
    return 0
}

section "SESSION 3 ASYNC-LIFECYCLE HARDWARE REGRESSION"

echo "Date:          $(date)"
echo "Expected UUID: $EXPECTED_UUID"
echo "SSID:          $SSID"
echo "Interface:     $IFACE"
echo "Log:           $LOG"

section "1. VERIFY TEST TOOL"

if [[ -x "$RTW" ]]; then
    pass "rtw88ctl exists"
else
    fail "rtw88ctl missing: $RTW"
    exit 1
fi

section "2. VERIFY EXACT SESSION 3 KEXT"

LOADED="$(kmutil showloaded 2>/dev/null | grep 'com\.rtw88\.driver' || true)"
echo "$LOADED"

if [[ -z "$LOADED" ]]; then
    fail "com.rtw88.driver is not loaded"
    exit 1
fi

pass "rtw88 kext loaded"

if echo "$LOADED" | grep -q "$EXPECTED_UUID"; then
    pass "Session 3 UUID confirmed"
else
    fail "wrong loaded kext UUID"
    echo "Expected: $EXPECTED_UUID"
    exit 1
fi

section "3. INITIAL STATUS"

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q 'Card:.*RTL8821CE'; then
    pass "RTL8821CE initialized"
else
    fail "RTL8821CE not reported"
    exit 1
fi

if echo "$OUT" | grep -q 'Power:.*on'; then
    pass "radio powered on"
else
    fail "radio not powered on"
    exit 1
fi

if echo "$OUT" | grep -q '^State:.*connected'; then
    echo "Disconnecting existing connection..."
    "$RTW" disconnect || true
    sleep 2
fi

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*idle'; then
    pass "initial idle state confirmed"
else
    fail "driver did not reach idle"
    exit 1
fi

section "4. INITIAL SCAN"

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
    pass "BSSID confirmed"
else
    fail "BSSID mismatch"
fi

if echo "$TARGET" | grep -Eq '[[:space:]]36[[:space:]]+WPA2'; then
    pass "channel 36 / WPA2 confirmed"
else
    fail "channel/security mismatch"
fi

RSSI="$(echo "$TARGET" | grep -oE -- '-[0-9]+ dBm' | head -1)"

if [[ -n "$RSSI" ]]; then
    pass "scan RSSI plausible: $RSSI"
else
    fail "scan RSSI invalid"
fi

section "5. INITIAL CONNECT + DHCP"

if connect_and_wait; then
    pass "initial WPA2 connection + DHCP succeeded"
else
    fail "initial connection/DHCP failed"
    exit 1
fi

OUT="$(driver_status)"
echo "$OUT"

IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"
GATEWAY="$(get_gateway)"

if [[ -z "$GATEWAY" ]]; then
    GATEWAY="192.168.1.1"
    warn "DHCP gateway parse failed; using known gateway $GATEWAY"
else
    pass "gateway detected: $GATEWAY"
fi

section "6. INITIAL GATEWAY TEST"

if ping -S "$IP" -c 10 "$GATEWAY"; then
    pass "initial gateway ping passed"
else
    fail "initial gateway ping failed"
    exit 1
fi

section "7. LARGE HTTP TRANSFER"

URLS=(
    'https://proof.ovh.net/files/10Mb.dat'
    'https://speed.hetzner.de/10MB.bin'
    'https://speed.cloudflare.com/__down?bytes=10000000'
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

    warn "endpoint failed; trying next"
done

if (( ! TRANSFER_OK )); then
    fail "all large-transfer endpoints failed"
fi

OUT="$(driver_status)"
echo
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*connected'; then
    pass "connection remained up under traffic"
else
    fail "connection dropped during traffic"
fi

RSSI="$(echo "$OUT" | awk '/^RSSI:/ {print $2; exit}')"

if [[ "$RSSI" == -* ]]; then
    pass "post-traffic RSSI plausible: ${RSSI} dBm"
else
    fail "post-traffic RSSI invalid"
fi

section "8. DISCONNECT + RECONNECT"

"$RTW" disconnect
sleep 2

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*idle'; then
    pass "disconnect returned to idle"
else
    fail "disconnect did not return idle"
fi

if connect_and_wait; then
    pass "reconnect succeeded"
else
    fail "reconnect failed"
    exit 1
fi

IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if ping -S "$IP" -c 5 "$GATEWAY"; then
    pass "gateway works after reconnect"
else
    fail "gateway failed after reconnect"
fi

section "9. RADIO POWER OFF"

"$RTW" disconnect || true
sleep 1

if "$RTW" power off; then
    pass "power-off command completed"
else
    fail "power-off command failed"
fi

sleep 3

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q 'Power:.*off'; then
    pass "radio reports off"
else
    fail "radio did not report off"
fi

section "10. RADIO POWER ON"

if "$RTW" power on; then
    pass "power-on command completed"
else
    fail "power-on command failed"
    exit 1
fi

sleep 3

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q 'Power:.*on'; then
    pass "radio reports on"
else
    fail "radio did not report on"
fi

section "11. SCAN AFTER RADIO CYCLE"

if "$RTW" scan -w 10; then
    pass "post-power-cycle scan completed"
else
    fail "post-power-cycle scan failed"
    exit 1
fi

LIST="$("$RTW" list 2>&1)"
echo "$LIST"

if echo "$LIST" | grep -Fq "$SSID"; then
    pass "$SSID visible after radio cycle"
else
    fail "$SSID missing after radio cycle"
    exit 1
fi

section "12. RECONNECT AFTER RADIO CYCLE"

if connect_and_wait; then
    pass "reconnect after radio cycle succeeded"
else
    fail "reconnect after radio cycle failed"
    exit 1
fi

IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if ping -S "$IP" -c 5 "$GATEWAY"; then
    pass "gateway works after radio cycle"
else
    fail "gateway failed after radio cycle"
fi

section "13. FIVE DISCONNECT / RECONNECT CYCLES"

for cycle in {1..5}; do
    echo
    echo "---------------- CYCLE $cycle / 5 ----------------"

    if "$RTW" disconnect; then
        pass "cycle $cycle disconnect command completed"
    else
        fail "cycle $cycle disconnect command failed"
        continue
    fi

    sleep 1

    OUT="$(driver_status)"

    if echo "$OUT" | grep -q '^State:.*idle'; then
        pass "cycle $cycle idle after disconnect"
    else
        fail "cycle $cycle not idle after disconnect"
    fi

    if connect_and_wait; then
        pass "cycle $cycle reconnect succeeded"
    else
        fail "cycle $cycle reconnect failed"
        continue
    fi

    IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

    if ping -S "$IP" -c 3 "$GATEWAY"; then
        pass "cycle $cycle gateway traffic passed"
    else
        fail "cycle $cycle gateway traffic failed"
    fi

    OUT="$(driver_status)"
    RSSI="$(echo "$OUT" | awk '/^RSSI:/ {print $2; exit}')"

    if [[ "$RSSI" == -* ]]; then
        pass "cycle $cycle RSSI plausible: ${RSSI} dBm"
    else
        fail "cycle $cycle RSSI invalid"
    fi
done

section "14. FINAL CONNECTED STATUS"

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*connected'; then
    pass "final state connected"
else
    fail "final state not connected"
fi

IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if [[ -n "$IP" && "$IP" != 169.254.* ]] &&
   ping -S "$IP" -c 5 "$GATEWAY"; then
    pass "final gateway test passed"
else
    fail "final gateway test failed"
fi

section "15. FINAL CLEAN DISCONNECT"

"$RTW" disconnect
sleep 2

OUT="$(driver_status)"
echo "$OUT"

if echo "$OUT" | grep -q '^State:.*idle'; then
    pass "final clean idle state"
else
    fail "final state not idle"
fi

section "RESULT"

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
    echo
    echo "Session 3 async-lifecycle candidate passed hardware regression."
    echo "No sleep/wake testing was performed."
    echo "================================================================"
    exit 0
else
    echo
    echo "================================================================"
    echo "OVERALL RESULT: FAIL"
    echo
    echo "Do NOT start Session 4."
    echo "================================================================"
    exit 1
fi
