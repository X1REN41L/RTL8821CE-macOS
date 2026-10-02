# Compatibility list

Machines confirmed with RTL88WiFi. To add yours, run
`bash tools/rtl88wifi-check.sh --speed` and open a
[compatibility report](../../../issues/new?template=compatibility-report.yml).
Confirmed reports are added here.

Status: ✅ works · 🟡 works with issues · ❌ does not work

| Chip (PCI ID) | Machine | macOS | RTL88WiFi | Band / security | Status | Notes |
|---|---|---|---|---|---|---|
| RTL8821CE (`10ec:c821`) | HP 15-da0003tu laptop, i3-8130U | Sonoma 14.8.9 (23J631) | 1.0.0 | 5 GHz ch 36, WPA2/WPA3 mixed | ✅ | 86–87 down / 89–105 up Mbps; sleep/wake, rekeys, network switching |

## Wanted

| Chip | PCI ID | Reports so far |
|---|---|---|
| RTL8822BE | `10ec:b822` | none yet |
| RTL8822CE | `10ec:c822`, `10ec:c82f` | none yet |
| RTL8821CE on Sequoia 15 / Tahoe 26 | `10ec:c821`, `10ec:b821` | none yet |
| Any chip on Ventura 13.7.7–13.7.8 | | none yet |
