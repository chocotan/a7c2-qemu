/* SPDX-License-Identifier: MIT */
#ifndef A7C2_SYSTEM_SOUND_OWNER_H
#define A7C2_SYSTEM_SOUND_OWNER_H
#define SYSTEM_SOUND_PHYSICAL 0x41d000000ULL
#define SYSTEM_SOUND_BUS 0x1d000000ULL
#define SYSTEM_SOUND_AUDIO_PHYS64 0x81d000000ULL
#define SYSTEM_SOUND_CAPACITY 0x20000UL
#define SYSTEM_SOUND_BYTES 0x10340UL
#define SYSTEM_SOUND_FNV 0x0500159a93ab9e42ULL
#define SYSTEM_SOUND_SHA256 "5d94c660c48afde364fbb936105abdaf5c35f8bf8fc0bfd6945cd12146f6824a"
#define SYSTEM_SOUND_RESERVATION "memrsv=0x00020000@0x41d000000:uc"
/* Explicit virtual owner: AUDIO_PHYS64 follows the ADF [800000000,880000000)
 * phys64->CPU-offset window, BUS is the modeled CPU offset, and PHYSICAL is
 * this VM's separately reserved backing. This is not proof of the original
 * boot loader's allocation or a physical CP-CPU alias. Lifetime is the VM. */
unsigned long long system_sound_digest(const volatile unsigned char *, unsigned long);
int system_sound_load(volatile unsigned char *, unsigned long,
                      const unsigned char *, unsigned long);
int system_sound_verify(const volatile unsigned char *, unsigned long,
                        const unsigned char *, unsigned long);
#endif
