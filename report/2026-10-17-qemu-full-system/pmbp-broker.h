/* SPDX-License-Identifier: MIT */
#ifndef PMBP_BROKER_H
#define PMBP_BROKER_H
#include "pmbp-candidate.h"
#define PMBP_FILE_LIMIT 16u
#define PMBP_WINDOW_LIMIT 128u
#define PMBP_DISK_BYTES UINT64_C(1962934272)
/* Fixed little-endian LP64 wire, zero padding is required; not a public setter. */
struct pmbp_manifest {
 unsigned char magic[8];
 uint32_t schema, profile;
 uint64_t generation, lease_epoch, disk_dev, disk_ino, disk_bytes, offset, bytes, selector;
 unsigned char instance_sha[32], geometry_sha[32], parent_profile_sha[32], source_sha[32];
 unsigned char module_sha[32], hostcore_sha[32], driver_sha[32], bootstrap_sha[32];
 uint64_t module_bytes, parent_pid, parent_starttime;
 char vermagic[128];
};
struct pmbp_runtime_marker {
 unsigned char magic[8], manifest_sha[32], source_sha[32], code_sha[32], module_sha[32];
 uint64_t pid,starttime,lease_epoch;
 int32_t insmod_rc;
 uint32_t reserved;
};
struct pmbp_file_pin { const char *path; uint64_t bytes; unsigned char sha[32]; };
struct pmbp_window_pin {
 const char *symbol;
 unsigned file;
 uint64_t symbol_va, va, bytes, caller_va;
 unsigned operation;
 const unsigned char *code;
};
/* Every field's provenance is explicit; no runtime offset observation is claimed. */
struct pmbp_broker_state {
 int admission_errno, enabled, hardware_attested;
 uint64_t starttime, claimed_tid, epoch;
 unsigned host_provisioned, source_derived, runtime_blockquery;
 unsigned module_memory_hash_known;
};
struct pmbp_broker_state pmbp_broker_status(void);
int pmbp_broker_checked(const char *checked_root,const char *manifest_name);
int pmbp_broker_caller(enum pmbp_operation,uintptr_t);
int pmbp_broker_native(const char *,void *);
int pmbp_regular_span(uintptr_t,size_t);
int pmbp_copy_info(uintptr_t caller,uintptr_t frame,uintptr_t buffer,uint32_t rc,uint32_t *word);
int pmbp_mutex_scope(int entering,int device);
void pmbp_mutex_result(uintptr_t caller,void *mutex,int rc,int unlocking);
int pmbp_format_scope(int entering,uintptr_t caller);
unsigned pmbp_retry_ordinal(void);
void pmbp_checkpoint(const char *,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,long,int,unsigned,uint32_t);
/* Existing observer saves original LR/frame in its exported frame before lookup. */
uint32_t pmbp_native6_at(const char *,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t,uintptr_t);
/* Used by the small bootstrap executable, never an fd-adoption API. */
int pmbp_bootstrap(int argc,char **argv);
#endif
