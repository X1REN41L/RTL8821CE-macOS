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
EXPECTED_CHANNEL="36"

LOG="$HOME/Desktop/rtw88-session2-$(date +%Y%m%d-%H%M%S).log"

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

get_driver_status() {
    "$RTW" status 2>&1
}

section "SESSION 2 ACTIVE-PCI ABI HARDWARE REGRESSION"

echo "Date:          $(date)"
echo "SSID:          $SSID"
echo "Interface:     $IFACE"
echo "Expected UUID: $EXPECTED_UUID"
echo "Log:           $LOG"

section "1. VERIFY TOOL"

if [[ -x "$RTW" ]]; then
    pass "rtw88ctl exists"
else
    fail "rtw88ctl missing"
    exit 1
fi

section "2. VERIFY LOADED SESSION 2 KEXT"

LOADED="$(kmutil showloaded 2>/dev/null | grep 'com\.rtw88\.driver' || true)"

echo "$LOADED"

if [[ -z "$LOADED" ]]; then
    fail "com.rtw88.driver is not loaded"
    exit 1
fi

pass "com.rtw88.driver is loaded"

if echo "$LOADED" | grep -q "$EXPECTED_UUID"; then
    pass "loaded UUID matches Session 2 candidate"
else
    fail "loaded UUID does not match Session 2 candidate"
    echo "Expected: $EXPECTED_UUID"
    exit 1
fi

section "3. VERIFY DRIVER INITIALIZATION"

DRIVER_STATUS="$(get_driver_status)"
echo "$DRIVER_STATUS"

if echo "$DRIVER_STATUS" | grep -q 'Card:.*RTL8821CE'; then
    pass "RTL8821CE initialized"
else
    fail "RTL8821CE card not reported"
    exit 1
fi

if echo "$DRIVER_STATUS" | grep -q 'Power:.*on'; then
    pass "radio power is on"
else
    fail "radio is not powered on"
    exit 1
fi

section "4. GET TO IDLE STATE"

if echo "$DRIVER_STATUS" | grep -q '^State:.*connected'; then
    echo "Existing connection found; disconnecting before scan..."
    "$RTW" disconnect || true
    sleep 2
fi

DRIVER_STATUS="$(get_driver_status)"
echo "$DRIVER_STATUS"

if echo "$DRIVER_STATUS" | grep -q '^State:.*idle'; then
    pass "driver is idle before scan"
else
    warn "driver state is not explicitly idle before scan"
fi

section "5. SCAN"

if "$RTW" scan -w 10; then
    pass "scan command completed"
else
    fail "scan command failed"
    exit 1
fi

echo
NETWORKS="$("$RTW" list 2>&1)"
echo "$NETWORKS"

TARGET_LINE="$(echo "$NETWORKS" | grep -F "$SSID" | head -1)"

if [[ -z "$TARGET_LINE" ]]; then
    fail "$SSID was not found"
    exit 1
fi

echo
echo "Target AP:"
echo "$TARGET_LINE"

pass "$SSID found"

if echo "$TARGET_LINE" | grep -Fq "$EXPECTED_BSSID"; then
    pass "BSSID matches $EXPECTED_BSSID"
else
    fail "unexpected BSSID"
fi

if echo "$TARGET_LINE" | grep -Eq "[[:space:]]${EXPECTED_CHANNEL}[[:space:]]+WPA2"; then
    pass "channel $EXPECTED_CHANNEL and WPA2 confirmed"
else
    fail "expected channel/security not confirmed"
fi

SCAN_RSSI="$(echo "$TARGET_LINE" | grep -oE -- '-[0-9]+ dBm' | head -1)"

if [[ -n "$SCAN_RSSI" ]]; then
    pass "scan RSSI plausible: $SCAN_RSSI"
else
    fail "scan RSSI is missing or invalid"
fi

section "6. CONNECT"

"$RTW" connect "$SSID" "$PASSWORD"

CONNECTED=0

for i in {1..15}; do
    DRIVER_STATUS="$(get_driver_status)"
    STATE="$(echo "$DRIVER_STATUS" | awk '/^State:/ {print $2; exit}')"

    echo "[$i/15] state=$STATE"

    if [[ "$STATE" == "connected" ]]; then
        CONNECTED=1
        break
    fi

    sleep 1
done

if (( CONNECTED )); then
    pass "WPA2 connection established"
else
    fail "connection failed"
    echo "$DRIVER_STATUS"
    exit 1
fi

echo
echo "$DRIVER_STATUS"

CONNECTED_RSSI="$(echo "$DRIVER_STATUS" | awk '/^RSSI:/ {print $2; exit}')"

if [[ "$CONNECTED_RSSI" == -* ]]; then
    pass "connected RSSI plausible: ${CONNECTED_RSSI} dBm"
else
    fail "connected RSSI invalid"
fi

section "7. DHCP / IPV4"

IP=""

for i in {1..10}; do
    IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

    if [[ -n "$IP" ]]; then
        break
    fi

    sleep 1
done

if [[ -n "$IP" ]]; then
    echo "IPv4: $IP"
    pass "IPv4 address acquired"
else
    fail "no IPv4 address acquired on $IFACE"
    exit 1
fi

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

if [[ -z "$GATEWAY" ]]; then
    GATEWAY="192.168.1.1"
    warn "could not parse gateway; using known test gateway $GATEWAY"
else
    pass "gateway detected: $GATEWAY"
fi

section "8. GATEWAY CONNECTIVITY"

if ping -S "$IP" -c 10 "$GATEWAY"; then
    pass "10/10 gateway test completed"
else
    fail "gateway ping test failed"
fi

section "9. 10 MB INTERNET TRANSFER"

BEFORE_STATUS="$(get_driver_status)"
echo "--- BEFORE ---"
echo "$BEFORE_STATUS"

CURL_OUTPUT="$(
    curl \
        --interface "$IFACE" \
        -4 \
        --connect-timeout 10 \
        --max-time 90 \
        -sS \
        -o /dev/null \
        -w '%{size_download}|%{speed_download}|%{time_total}|%{http_code}' \
        'https://speed.cloudflare.com/__down?bytes=10000000'
)"

CURL_RC=$?

SIZE="$(echo "$CURL_OUTPUT" | cut -d'|' -f1)"
SPEED="$(echo "$CURL_OUTPUT" | cut -d'|' -f2)"
TOTAL_TIME="$(echo "$CURL_OUTPUT" | cut -d'|' -f3)"
HTTP="$(echo "$CURL_OUTPUT" | cut -d'|' -f4)"

echo
echo "Downloaded: $SIZE bytes"
echo "Speed:      $SPEED B/s"
echo "Time:       $TOTAL_TIME s"
echo "HTTP:       $HTTP"

if (( CURL_RC == 0 )) &&
   [[ "$SIZE" == "10000000" ]] &&
   [[ "$HTTP" == "200" ]]; then
    pass "10 MB transfer completed with HTTP 200"
else
    fail "10 MB transfer failed"
fi

section "10. POST-TRAFFIC STATUS"

AFTER_STATUS="$(get_driver_status)"
echo "$AFTER_STATUS"

if echo "$AFTER_STATUS" | grep -q '^State:.*connected'; then
    pass "connection remained up after traffic"
else
    fail "connection dropped during traffic"
fi

FINAL_RSSI="$(echo "$AFTER_STATUS" | awk '/^RSSI:/ {print $2; exit}')"

if [[ "$FINAL_RSSI" == -* ]]; then
    pass "post-traffic RSSI plausible: ${FINAL_RSSI} dBm"
else
    fail "post-traffic RSSI invalid"
fi

BEFORE_TX="$(echo "$BEFORE_STATUS" | awk '/^TX Bytes:/ {print $3; exit}')"
BEFORE_RX="$(echo "$BEFORE_STATUS" | awk '/^RX Bytes:/ {print $3; exit}')"

AFTER_TX="$(echo "$AFTER_STATUS" | awk '/^TX Bytes:/ {print $3; exit}')"
AFTER_RX="$(echo "$AFTER_STATUS" | awk '/^RX Bytes:/ {print $3; exit}')"

echo
echo "TX before: ${BEFORE_TX:-unknown}"
echo "TX after:  ${AFTER_TX:-unknown}"
echo "RX before: ${BEFORE_RX:-unknown}"
echo "RX after:  ${AFTER_RX:-unknown}"

if [[ "$BEFORE_RX" == <-> && "$AFTER_RX" == <-> ]] &&
   (( AFTER_RX > BEFORE_RX )); then
    pass "RX counters advanced"
else
    warn "could not confirm RX counter advancement"
fi

section "11. FINAL GATEWAY CHECK"

IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if [[ -n "$IP" ]] && ping -S "$IP" -c 5 "$GATEWAY"; then
    pass "final gateway connectivity passed"
else
    fail "final gateway connectivity failed"
fi

section "12. CLEAN DISCONNECT"

if "$RTW" disconnect; then
    pass "disconnect command completed"
else
    fail "disconnect command failed"
fi

sleep 2

END_STATUS="$(get_driver_status)"
echo
echo "$END_STATUS"

if echo "$END_STATUS" | grep -q '^State:.*idle'; then
    pass "driver returned to idle"
else
    fail "driver did not return to idle"
fi

section "RESULT SUMMARY"

echo "PASS checks: $PASS_COUNT"
echo "FAIL checks: $FAIL_COUNT"
echo "WARN checks: $WARN_COUNT"

echo
echo "Log saved to:"
echo "$LOG"

if (( FAIL_COUNT == 0 )); then
    echo
    echo "================================================================"
    echo "OVERALL RESULT: PASS"
    echo
    echo "Session 2 candidate passed the required hardware regression."
    echo "Candidate can become the new hardware-validated baseline."
    echo "================================================================"
    exit 0
else
    echo
    echo "================================================================"
    echo "OVERALL RESULT: FAIL"
    echo
    echo "Do NOT start Session 3."
    echo "================================================================"
    exit 1
fi
