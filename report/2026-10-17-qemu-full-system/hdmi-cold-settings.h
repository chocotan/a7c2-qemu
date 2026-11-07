/* SPDX-License-Identifier: MIT */
#ifndef HDMI_COLD_SETTINGS_H
#define HDMI_COLD_SETTINGS_H
struct hdmi_backup_api {
    unsigned int (*get_size)(unsigned int);
    unsigned int (*nread)(unsigned int,void *,int);
    void (*record)(const char *,const char *);
};
struct hdmi_cold_settings {
    unsigned char initial[18],config[36];
    unsigned int read_mask,default_mask;
    unsigned int key_10704fd,flag_9a0009,flag_9a000a,byte_9a000b,delay_9a000c;
};
/* Bind callbacks to original Backup_get_datasize/Backup_nread. Optional
 * original_default28 must be verified private firmware data, never invented
 * zeros; NULL rejects only when that fallback is actually required. Output
 * storage must be independent of the API object and fallback bytes. */
int hdmi_cold_settings_read(const struct hdmi_backup_api *,const unsigned char *original_default28,
                            struct hdmi_cold_settings *);
#endif
