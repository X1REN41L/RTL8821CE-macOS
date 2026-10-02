# Building AirPort_RTW88 2.0.1 from source

`AirPort_RTW88-2.0.1.patch` contains every change from AirPort_RTW88 2.0.0 to
2.0.1. It applies to `AirPort_RTW88-Source.zip` from
[xnoah222/Realtek-AirPort-Family](https://github.com/xnoah222/Realtek-AirPort-Family).

The prebuilt kext in [`../Kexts/AirPort_RTW88.kext`](../Kexts/AirPort_RTW88.kext)
was built this way. Its binary SHA-256 is
`da48418920dccbcb69dc0529ec35b4616b84fa47cff80f641ce572354f199659`.

## Requirements

- macOS with Xcode or the Xcode Command Line Tools (`xcrun clang`)
- `python3` (generates the embedded firmware blobs)

## Steps

```sh
unzip AirPort_RTW88-Source.zip -x '__MACOSX/*'
cd AirPort_RTW88
git apply /path/to/AirPort_RTW88-2.0.1.patch
cd Feixiao
make airport
```

The kext is written to `Feixiao/build/out/AirPort_RTW88.kext`. The Realtek
firmware (`Feixiao/firmware/rtw88*_fw.bin`, included in the source zip) is
compressed into the kext binary at build time, so the kext needs no separate
firmware files.

Use `make airport` only. Do not use `make install` or `make load`: on Sonoma
the kext must be injected by OpenCore (see the main README).

## Files changed by the patch

```text
Feixiao/AirPort_RTW88.kext/Contents/Info.plist                  |   6
Feixiao/MacKernelSDK/Headers/IOKit/80211/apple80211_ioctl.h     |   4
Feixiao/src/compat/linux/skbuff.h                               |   4
Feixiao/src/compat/net/mac80211.h                               |   8
Feixiao/src/compat/rtw88_compat.c                               | 148
Feixiao/src/compat/rtw88_compat.h                               |   6
Feixiao/src/compat/rtw88_firmware.c                             |  26
Feixiao/src/kext/AirportRTW88.cpp                               | 270
Feixiao/src/kext/AirportRTW88.hpp                               |  18
Feixiao/src/kext/RTW88IEEE80211.cpp                             | 602
Feixiao/src/kext/RTW88IEEE80211.hpp                             |  18
Feixiao/src/kext/kmod_info.c                                    |   2
rtw88-stable/drivers/net/wireless/realtek/rtw88/tx.c            |   2
13 files changed, 1025 insertions(+), 89 deletions(-)
```
