/* Modified by X1REN41L on 2026-10-02 for RTL88WiFi 1.0.0; see the repository SOURCE-NOTICES.md. */
/* SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
 * RTL88WiFiKext.hpp — top-level IOService provider matching
 */
#pragma once

#include <IOKit/IOService.h>

class RTL88WiFiKext : public IOService {
    OSDeclareDefaultStructors(RTL88WiFiKext)

public:
    bool init(OSDictionary *props) override;
    bool start(IOService *provider) override;
    void stop(IOService *provider) override;
    void free() override;

    IOService *probe(IOService *provider, SInt32 *score) override;
};
