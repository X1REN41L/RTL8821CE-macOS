/* Modified by X1REN41L on 2026-10-02 for RTL88WiFi 1.0.0; see the repository SOURCE-NOTICES.md. */
/* SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
 * RTL88WiFiInterface.hpp — thin IO80211Interface, mirrors AirportItlwmInterface.
 *
 * This class does almost nothing on its own: it's the object macOS's
 * network stack / CoreWLAN sees as "the Wi-Fi interface". All real work
 * happens in RTL88WiFi (the IO80211Controller). We just need to
 * override inputPacket() so RX frames get delivered correctly with the
 * 802.11-aware framing IO80211Family expects.
 */
#pragma once

class IO80211FlowQueue;  /* falta en este snapshot del MacKernelSDK; solo se usa como puntero */
#include <IOKit/80211/IO80211Interface.h>

class RTL88WiFi;

class RTL88WiFiInterface : public IO80211Interface {
    OSDeclareDefaultStructors(RTL88WiFiInterface)

public:
    virtual UInt32 inputPacket(mbuf_t packet,
                                UInt32 length = 0,
                                IOOptionBits options = 0,
                                void *param = 0) override;

    bool init(IONetworkController *controller) override;
};
