/* SPDX-License-Identifier: GPL-2.0 OR BSD-3-Clause
 * Master compatibility header for rtw88 macOS port.
 * Every driver .c file that includes linux/ or net/ headers ends up here
 * via the -I src/compat include path override in the Makefile.
 */
#ifndef _RTW88_COMPAT_H
#define _RTW88_COMPAT_H

/* GCC/clang attribute stubs not available on macOS kernel */
#ifndef __nonstring
#define __nonstring
#endif
/* __cold and __pure may be defined by sys/cdefs.h — guard and redefine */
#ifdef __cold
#undef __cold
#endif
#define __cold __attribute__((cold))
#ifdef __pure
#undef __pure
#endif
#define __pure __attribute__((pure))
#ifndef fallthrough
#if defined(__clang__) || (defined(__GNUC__) && __GNUC__ >= 7)
#define fallthrough __attribute__((__fallthrough__))
#else
#define fallthrough do {} while (0)
#endif
#endif

/* Pull in all compat headers in dependency order */
#include "iokit_shim.h"
#include "linux/types.h"
#include "linux/device.h"
#include "linux/bitops.h"
#include "linux/bitfield.h"
#include "linux/atomic.h"
#include "linux/kernel.h"
#include "linux/slab.h"
#include "linux/vmalloc.h"
#include "linux/jiffies.h"
#include "linux/delay.h"
#include "linux/iopoll.h"
#include "linux/average.h"
#include "linux/spinlock.h"
#include "linux/mutex.h"
#include "linux/completion.h"
#include "linux/timer.h"
#include "linux/workqueue.h"
#include "linux/if_ether.h"
#include "linux/etherdevice.h"
#include "linux/skbuff.h"
#include "linux/interrupt.h"
#include "linux/netdevice.h"
#include "linux/firmware.h"
#include "linux/dma-mapping.h"
#include "linux/pci.h"
#include "linux/usb.h"
#include "linux/module.h"
#include "linux/leds.h"
#include "linux/devcoredump.h"
#include "linux/seq_file.h"
#include "net/mac80211.h"

/* ------------------------------------------------------------------ */
/*  Missing RTW88 driver bits that mac80211.h references               */
/* ------------------------------------------------------------------ */

struct rtw_dev;

void get_random_mask_addr(u8 *buf, const u8 *addr, const u8 *mask);

/* dev_err / dev_warn / dev_info / dev_dbg */
void rtw88_dev_printk(int level, struct device *dev, const char *fmt, ...)
    __attribute__((format(printf, 3, 4)));

#define dev_err(dev, fmt, ...)  rtw88_dev_printk(KERN_ERR,   dev, fmt, ##__VA_ARGS__)
#define dev_warn(dev, fmt, ...) rtw88_dev_printk(KERN_WARN,  dev, fmt, ##__VA_ARGS__)
#define dev_info(dev, fmt, ...) rtw88_dev_printk(KERN_INFO,  dev, fmt, ##__VA_ARGS__)
#define dev_dbg(dev, fmt, ...)  rtw88_dev_printk(KERN_DEBUG, dev, fmt, ##__VA_ARGS__)

/* devcoredump used in main.c */
#define dev_coredump(dev, data, datalen, gfp) dev_coredumpv(dev, data, datalen, gfp)

/* rculist stubs — used in some rtw88 files */
#define rcu_read_lock()   do {} while (0)
#define rcu_read_unlock() do {} while (0)
#define rcu_dereference(p) (p)
#define rcu_dereference_protected(p, c) (p)
#define RCU_INIT_POINTER(p, v) ((p) = (v))
#define rcu_assign_pointer(p, v) ((p) = (v))
#define synchronize_rcu() do {} while (0)

/* srcu stubs */
struct srcu_struct { int dummy; };
#define __SRCU_DEP_MAP_INIT(name)
#define DEFINE_STATIC_SRCU(name) struct srcu_struct name
static inline int srcu_read_lock(struct srcu_struct *s) { return 0; }
static inline void srcu_read_unlock(struct srcu_struct *s, int idx) {}
static inline void synchronize_srcu(struct srcu_struct *s) {}

/* refcount */
typedef atomic_t refcount_t;
#define refcount_set(r, v)  atomic_set(r, v)
#define refcount_read(r)    atomic_read(r)
#define refcount_inc(r)     atomic_inc(r)
#define refcount_dec_and_test(r) atomic_dec_and_test(r)

/* nl80211 reason codes */
#define WLAN_REASON_UNSPECIFIED             1
#define WLAN_REASON_DEAUTH_LEAVING          3
#define WLAN_REASON_DISASSOC_DUE_TO_INACTIVITY 4
#define WLAN_REASON_4WAY_HANDSHAKE_TIMEOUT  15
#define WLAN_REASON_GROUP_KEY_UPDATE_TIMEOUT 16
#define WLAN_REASON_IE_IN_4WAY_DIFFERS      17

/* nl80211 status codes */
#define WLAN_STATUS_SUCCESS              0
#define WLAN_STATUS_UNSPECIFIED_FAILURE  1
#define WLAN_STATUS_CAPS_UNSUPPORTED     10

/* WMM/QoS */
#define IEEE80211_MAX_QUEUES  4

/* IEEE80211 element IDs */
#define WLAN_EID_SSID                0
#define WLAN_EID_SUPP_RATES          1
#define WLAN_EID_DS_PARAMS           3
#define WLAN_EID_TIM                 5
#define WLAN_EID_IBSS_PARAMS         6
#define WLAN_EID_COUNTRY             7
#define WLAN_EID_RSN                48
#define WLAN_EID_HT_CAPABILITY       45
#define WLAN_EID_HT_OPERATION        61
#define WLAN_EID_VHT_CAPABILITY     191
#define WLAN_EID_VHT_OPERATION      192
#define WLAN_EID_EXT_CAPABILITY      127
#define WLAN_EID_EXT_SUPP_RATES      50
#define WLAN_EID_VENDOR_SPECIFIC     221

/* Action-frame categories / BlockAck actions (802.11 BlockAck, category 3).
 * Used by the MLME to negotiate A-MPDU aggregation over the air. */
#define WLAN_CATEGORY_BACK           3
#define WLAN_ACTION_ADDBA_REQ        0
#define WLAN_ACTION_ADDBA_RESP       1
#define WLAN_ACTION_DELBA            2

/* ------------------------------------------------------------------ */
/*  Compat global state init/exit                                       */
/* ------------------------------------------------------------------ */

int  rtw88_compat_init(void);
void rtw88_compat_exit(void);

/* Set the firmware resources directory (call before rtw_pci_probe) */
void rtw88_set_fw_dir(const char *dir);
/* Auto-detect firmware directory from boot-args or well-known paths */
void rtw88_find_fw_dir(void);

void rtw88_get_fw_version(struct rtw_dev *rtwdev, uint16_t *version, uint8_t *sub_version);
void rtw88_get_chip_name(struct rtw_dev *rtwdev, char *name_buf, size_t buf_sz);
void rtw88_get_stats(struct rtw_dev *rtwdev, uint32_t *tx_bytes, uint32_t *rx_bytes);
uint32_t rtw88_read_log(char *out_buf, uint32_t max_len);

void rtw88_reenable_interrupt(void);

/* Dump BE TX ring + interrupt state to IOLog. Called periodically by the
 * kext's debug timer to diagnose TX freeze; see rtw88_compat.c. */
void rtw88_debug_dump_tx_state(void);

/* Force-disable BT coexistence by clearing efuse.btcoex. Must be called
 * between rtw_pci_probe and the chip's start() op. See rtw88_compat.c. */
void rtw88_force_wifi_only(void);

/* TX flow control. rtw88_be_tx_avail() returns the BE ring's free-slot count
 * so the output path can stall (backpressure) instead of dropping when full.
 * rtw88_set_tx_resume_cb() registers a hook fired after each IRQ bottom-half
 * (post tx_isr, no locks held) so the kext can resume a stalled queue. */
unsigned int rtw88_be_tx_avail(void);
void rtw88_set_tx_resume_cb(void (*cb)(void));

/* Aggregate active-PCI TX diagnostics.  These are deliberately counters and
 * snapshots rather than per-frame logging so a sustained-transfer failure can
 * be observed without materially changing its timing. */
struct rtw88_tx_diag_snapshot {
    u64 submitted_frames;
    u64 submitted_bytes;
    u64 completed_frames;
    u64 completed_bytes;
    u64 ampdu_frames;
    u64 non_ampdu_frames;
    u64 encrypted_frames;
    u64 report_statuses;
    u64 report_acked;
    u64 dma_maps;
    u64 dma_map_failures;
    u64 dma_unmaps;
    u64 irq_bottom_halves;
    u64 output_stalls;
    u64 output_resumes;
    u64 output_stalled;
    u64 ra_mask;
    u64 last_ccmp_pn;
    u16 last_data_seq;
    u8 rate_id;
    u8 bandwidth;
    u8 vht_enabled;
    u8 sgi_enabled;
};
void rtw88_tx_diag_note_submit(u32 bytes, bool ampdu, bool encrypted,
                               u16 seq, u64 ccmp_pn);
void rtw88_tx_diag_note_completion(u32 bytes, bool report, bool acked);
void rtw88_tx_diag_note_dma_map(bool success);
void rtw88_tx_diag_note_dma_unmap(void);
void rtw88_tx_diag_note_irq_bottom_half(void);
void rtw88_tx_diag_note_output_stall(void);
void rtw88_tx_diag_note_output_resume(void);
void rtw88_tx_diag_capture_ra(void);
void rtw88_tx_diag_snapshot(struct rtw88_tx_diag_snapshot *out);

struct ieee80211_hw;
struct ieee80211_sta;
struct ieee80211_vif;

/* Returns true while the driver's RTW_FLAG_SCANNING bit is set.
 * Used by the kext to wait for post-scan MMIO cleanup before connecting. */
bool rtw88_is_scanning(void);
bool rtw88_hw_scan_supported(struct ieee80211_hw *hw);
void rtw88_sw_scan_start(struct ieee80211_hw *hw, struct ieee80211_vif *vif);
void rtw88_sw_scan_switch_channel(struct ieee80211_hw *hw);
void rtw88_sw_scan_complete(struct ieee80211_hw *hw, struct ieee80211_vif *vif);

/*
 * Configure channel + BSSID in the chip for the connect flow.
 * Bypasses rtw_ops_config / rtw_ops_bss_info_changed (and their
 * rtw_leave_lps_deep MMIO-read polling) to avoid post-scan PCIe hangs.
 * Caller must set hw->conf.chandef before calling.
 */
void rtw88_connect_hw_setup(struct ieee80211_hw *hw,
                             struct ieee80211_vif *vif,
                             const uint8_t *bssid);
void rtw88_restore_connected_hw(struct ieee80211_hw *hw,
                                 struct ieee80211_vif *vif,
                                 const uint8_t *bssid);

/* Quiesce every rtw_dev-owned work item before PCI removal frees rtwdev. */
void rtw88_cancel_device_work(struct rtw_dev *rtwdev);

/* Register the single active VIF so ieee80211_iterate_active_interfaces*
 * can call back into rtw88 internals (e.g. rtw_build_rsvd_page_iter for
 * the firmware reserved-page download after association). */
void rtw88_register_vif(struct ieee80211_vif *vif);
void rtw88_unregister_vif(void);
void rtw88_register_sta(struct ieee80211_vif *vif,
                        struct ieee80211_sta *sta);
void rtw88_unregister_sta(struct ieee80211_sta *sta);

#endif /* _RTW88_COMPAT_H */
