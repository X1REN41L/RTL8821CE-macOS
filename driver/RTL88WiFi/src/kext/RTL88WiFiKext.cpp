/* Modified by X1REN41L on 2026-10-02 for RTL88WiFi 1.0.0; see the repository SOURCE-NOTICES.md. */
// SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
// RTL88WiFiKext.cpp — top-level IOService, delegates to PCI or USB device classes

#include "RTL88WiFiKext.hpp"
#include <IOKit/IOLib.h>

#define super IOService
OSDefineMetaClassAndStructors(RTL88WiFiKext, IOService)

bool RTL88WiFiKext::init(OSDictionary *props)
{
    IOLog("rtw88: RTL88WiFiKext::init\n");
    return super::init(props);
}

IOService *RTL88WiFiKext::probe(IOService *provider, SInt32 *score)
{
    IOLog("rtw88: RTL88WiFiKext::probe\n");
    return super::probe(provider, score);
}

bool RTL88WiFiKext::start(IOService *provider)
{
    IOLog("rtw88: RTL88WiFiKext::start\n");
    if (!super::start(provider)) return false;
    registerService();
    return true;
}

void RTL88WiFiKext::stop(IOService *provider)
{
    IOLog("rtw88: RTL88WiFiKext::stop\n");
    super::stop(provider);
}

void RTL88WiFiKext::free()
{
    super::free();
}
