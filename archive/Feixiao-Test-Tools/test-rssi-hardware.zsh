#!/bin/zsh

set -u
setopt PIPE_FAIL

SCRIPT_DIR="${0:A:h}"
RTW="${RTW:-$SCRIPT_DIR/../Feixiao/build/out/rtw88ctl}"

SSID="${RTW_TEST_SSID:-RTW88_TEST_5GHz}"
PASS="${RTW_TEST_PASSWORD:-}"
: "${PASS:?Set RTW_TEST_PASSWORD before running this test}"
IFACE="en2"

EXPECTED_UUID="910FD77B-0C96-3F48-822C-60B16289D09B"
EXPECTED_SHA="4ba0f5d175c825a741fd95058555c9034301bce486429a1be83659140043c698"

DOWNLOAD_URL='https://speed.cloudflare.com/__down?bytes=10000000'
TRANSFERS=10

LOG="$HOME/Desktop/rtw88-rssi-test-$(date +%Y%m%d-%H%M%S).log"

exec > >(tee "$LOG") 2>&1

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0
ZERO_RSSI_COUNT=0

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

get_rssi() {
    get_status | awk '/^RSSI:/ {print $2; exit}'
}

get_state() {
    get_status | awk '/^State:/ {print $2; exit}'
}

check_rssi_now() {
    local label="$1"
    local rtw_status rssi

    rtw_status="$(get_status)"
    echo "$rtw_status" | grep -E 'State:|SSID:|BSSID:|RSSI:|Channel:|TX Bytes:|RX Bytes:' || true

    rssi="$(echo "$rtw_status" | awk '/^RSSI:/ {print $2; exit}')"

    if [[ -z "$rssi" ]]; then
        warn "$label: no RSSI field"
        return
    fi

    if [[ "$rssi" == "0" ]]; then
        fail "$label: RSSI became 0 dBm"
        (( ZERO_RSSI_COUNT++ ))
    elif [[ "$rssi" == -* ]]; then
        pass "$label: RSSI is plausible ($rssi dBm)"
    else
        warn "$label: unusual RSSI value: $rssi dBm"
    fi
}

cleanup_sampler() {
    if [[ -n "${SAMPLER_PID:-}" ]]; then
        kill "$SAMPLER_PID" 2>/dev/null || true
        wait "$SAMPLER_PID" 2>/dev/null || true
        unset SAMPLER_PID
    fi
}

trap cleanup_sampler EXIT INT TERM

section "RTL8821CE RSSI HARDWARE REGRESSION TEST"

echo "Date:        $(date)"
echo "Host:        $(hostname)"
echo "SSID:        $SSID"
echo "Interface:   $IFACE"
echo "Expected SHA:  $EXPECTED_SHA"
echo "Expected UUID: $EXPECTED_UUID"
echo "Log:         $LOG"

section "1. BASIC TOOL CHECK"

if [[ -x "$RTW" ]]; then
    pass "rtw88ctl exists"
else
    echo "rtw88ctl not found at:"
    echo "$RTW"
    exit 1
fi

section "2. VERIFY LOADED KEXT"

LOADED="$(kmutil showloaded 2>/dev/null | grep -i 'com\.rtw88\.driver' || true)"

if [[ -n "$LOADED" ]]; then
    echo "$LOADED"
    pass "com.rtw88.driver is loaded"
else
    fail "com.rtw88.driver is not loaded"
    echo
    echo "STOP: this does not appear to be the USB rtw88 test boot."
    exit 1
fi

if echo "$LOADED" | grep -qi "$EXPECTED_UUID"; then
    pass "loaded kext UUID matches Session 1 candidate"
else
    fail "loaded kext UUID does NOT match expected candidate"
    echo "Expected: $EXPECTED_UUID"
    exit 1
fi

section "3. INITIAL DRIVER STATUS"

get_status

if [[ "$(get_state)" == "idle" || "$(get_state)" == "connected" ]]; then
    pass "driver is responsive"
else
    fail "unexpected initial driver state"
fi

section "4. SCAN 5 GHz TEST AP"

echo "Starting scan..."
"$RTW" scan -w 10

echo
echo "--- NETWORK LIST ---"

LIST="$("$RTW" list 2>&1)"
echo "$LIST"

if echo "$LIST" | grep -Fq "$SSID"; then
    pass "$SSID found in scan"
else
    fail "$SSID not found"
    exit 1
fi

TARGET_LINE="$(echo "$LIST" | grep -F "$SSID" | head -1)"
echo
echo "Target scan entry:"
echo "$TARGET_LINE"

if echo "$TARGET_LINE" | grep -Eq '(^|[[:space:]])0[[:space:]]*dBm'; then
    fail "scan result reported 0 dBm"
    (( ZERO_RSSI_COUNT++ ))
else
    pass "scan result did not report 0 dBm"
fi

section "5. CONNECT"

"$RTW" debug 3 || warn "could not set debug level"

if [[ "$(get_state)" == "connected" ]]; then
    echo "Disconnecting existing connection first..."
    "$RTW" disconnect || true
    sleep 2
fi

"$RTW" connect "$SSID" "$PASS"

echo
echo "Waiting for connected state..."

CONNECTED=0

for i in {1..15}; do
    STATE="$(get_state)"

    echo "[$i/15] state=$STATE"

    if [[ "$STATE" == "connected" ]]; then
        CONNECTED=1
        break
    fi

    sleep 1
done

if (( CONNECTED )); then
    pass "connected to $SSID"
else
    fail "connection did not reach connected state"
    get_status
    exit 1
fi

section "6. INITIAL RSSI"

check_rssi_now "initial connected state"

section "7. DHCP / IPv4"

WIFI_IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if [[ -n "$WIFI_IP" ]]; then
    echo "Wi-Fi IPv4: $WIFI_IP"
    pass "IPv4 address assigned"
else
    fail "no IPv4 address on $IFACE"
    exit 1
fi

echo
ipconfig getpacket "$IFACE" 2>/dev/null || true

GATEWAY="$(
    ipconfig getpacket "$IFACE" 2>/dev/null |
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
    warn "could not parse DHCP router; using known test gateway $GATEWAY"
else
    echo "Gateway: $GATEWAY"
    pass "DHCP gateway detected"
fi

section "8. INITIAL GATEWAY TEST"

if ping -S "$WIFI_IP" -c 10 "$GATEWAY"; then
    pass "initial gateway ping passed"
else
    fail "initial gateway ping failed"
fi

section "9. HEAVY TRAFFIC + LIVE RSSI SAMPLING"

for (( n=1; n<=TRANSFERS; n++ )); do

    echo
    echo "################################################################"
    echo "TRANSFER $n / $TRANSFERS"
    echo "################################################################"

    check_rssi_now "transfer $n pre-traffic"

    SAMPLE_FILE="/tmp/rtw88-rssi-sample-$$-$n"
    : > "$SAMPLE_FILE"

    (
        SAMPLE=0

        while true; do
            (( SAMPLE++ ))

            STATUS="$("$RTW" status 2>/dev/null || true)"
            STATE="$(echo "$STATUS" | awk '/^State:/ {print $2; exit}')"
            RSSI="$(echo "$STATUS" | awk '/^RSSI:/ {print $2; exit}')"

            printf '[RSSI sample %02d] state=%-10s rssi=%s dBm\n' \
                "$SAMPLE" "${STATE:-unknown}" "${RSSI:-unknown}"

            if [[ "$RSSI" == "0" ]]; then
                echo "ZERO" >> "$SAMPLE_FILE"
            fi

            sleep 1
        done
    ) &

    SAMPLER_PID=$!

    CURL_RESULT="$(
        curl \
          --interface "$IFACE" \
          -4 \
          --connect-timeout 10 \
          --max-time 90 \
          -sS \
          -o /dev/null \
          -w '%{size_download}|%{speed_download}|%{time_total}|%{http_code}' \
          "$DOWNLOAD_URL"
    )"

    CURL_RC=$?

    cleanup_sampler

    echo

    SIZE="$(echo "$CURL_RESULT" | cut -d'|' -f1)"
    SPEED="$(echo "$CURL_RESULT" | cut -d'|' -f2)"
    TIME="$(echo "$CURL_RESULT" | cut -d'|' -f3)"
    HTTP="$(echo "$CURL_RESULT" | cut -d'|' -f4)"

    echo "Downloaded: $SIZE bytes"
    echo "Average speed: $SPEED B/s"
    echo "Total time: $TIME s"
    echo "HTTP: $HTTP"

    if (( CURL_RC == 0 )) && [[ "$HTTP" == "200" ]] && [[ "$SIZE" == "10000000" ]]; then
        pass "transfer $n completed: 10 MB / HTTP 200"
    else
        fail "transfer $n failed or returned unexpected result"
    fi

    ZERO_COUNT="$(grep -c '^ZERO$' "$SAMPLE_FILE" 2>/dev/null || true)"

    if (( ZERO_COUNT > 0 )); then
        fail "transfer $n observed RSSI 0 dBm during traffic ($ZERO_COUNT samples)"
        (( ZERO_RSSI_COUNT += ZERO_COUNT ))
    else
        pass "transfer $n had no 0 dBm RSSI samples"
    fi

    rm -f "$SAMPLE_FILE"

    if [[ "$(get_state)" == "connected" ]]; then
        pass "connection remained up after transfer $n"
    else
        fail "connection dropped after transfer $n"
    fi

    check_rssi_now "transfer $n post-traffic"

done

section "10. FINAL DRIVER STATUS"

get_status

if [[ "$(get_state)" == "connected" ]]; then
    pass "final state is connected"
else
    fail "final state is not connected"
fi

check_rssi_now "final state"

section "11. FINAL GATEWAY TEST"

WIFI_IP="$(ipconfig getifaddr "$IFACE" 2>/dev/null || true)"

if [[ -n "$WIFI_IP" ]] && ping -S "$WIFI_IP" -c 10 "$GATEWAY"; then
    pass "final gateway ping passed"
else
    fail "final gateway ping failed"
fi

section "12. RESULT SUMMARY"

echo "PASS checks:     $PASS_COUNT"
echo "FAIL checks:     $FAIL_COUNT"
echo "WARN checks:     $WARN_COUNT"
echo "0 dBm samples:   $ZERO_RSSI_COUNT"
echo
echo "Log saved to:"
echo "$LOG"
echo

if (( FAIL_COUNT == 0 && ZERO_RSSI_COUNT == 0 )); then
    echo "=============================================================="
    echo "OVERALL RESULT: PASS"
    echo
    echo "RSSI regression was NOT reproduced."
    echo "Connection and traffic remained functional."
    echo "Candidate is ready to be considered hardware-validated"
    echo "for the Session 1 RSSI fix."
    echo "=============================================================="
    exit 0
else
    echo "=============================================================="
    echo "OVERALL RESULT: FAIL"
    echo
    echo "Review failures above before Session 2."
    echo "Do NOT stack further driver changes yet."
    echo "=============================================================="
    exit 1
fi
