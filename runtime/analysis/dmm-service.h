#ifndef SONY_QEMU_DMM_SERVICE_H
#define SONY_QEMU_DMM_SERVICE_H
#define DMM_TEST_PHYSICAL 0x41e000000ULL
#define DMM_TEST_SIZE 0x100000U
/* Original AP/CP unit 0x62a -> extent 0x6db -> 0xbca0 bytes. */
#define DMM_LUT_PHYSICAL 0x41d020000ULL
#define DMM_LUT_SIZE 0xbca0U
#define DMM_LUT_MAP_SIZE 0x10000U
/* Indices 2..4 belong to functional-face-dmm; keep its handles distinct. */
#define DMM_LUT_INDEX 5U
#define DMM_LUT_RESERVATION "memrsv=0x00010000@0x41d020000:uc"
#define DMM_LUT_COMBINED_RESERVATION "memrsv=0x00030000@0x41d000000:uc"
enum dmm_creator_kind {
    DMM_CREATOR_UNKNOWN = 0,
    DMM_CREATOR_SPEECH_INITIAL = 1
};
struct dmm_slot {
    unsigned int handle, open_count, generation;
    int allocated;
    unsigned long long allocation_epoch;
    unsigned int creator_kind;
};
struct dmm_service {
    unsigned char *memory;
    unsigned long long physical;
    struct dmm_slot slots[2];
    unsigned long long allocations;
    unsigned int lifecycle_changed;
    unsigned char *lut_memory;
    unsigned long long lut_physical, lut_allocations;
    struct dmm_slot lut_slot;
    unsigned int lut_lifecycle_changed;
};
unsigned int dmm_speech_initial_creator(const unsigned long *elf_return_pcs, unsigned int count);
int dmm_service_reply(struct dmm_service *, const unsigned char *, unsigned int, unsigned char *);
#endif
