#ifndef SONY_QEMU_DMM_SERVICE_H
#define SONY_QEMU_DMM_SERVICE_H
#define DMM_TEST_PHYSICAL 0x41e000000ULL
#define DMM_TEST_SIZE 0x100000U
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
};
unsigned int dmm_speech_initial_creator(const unsigned long *elf_return_pcs, unsigned int count);
int dmm_service_reply(struct dmm_service *, const unsigned char *, unsigned int, unsigned char *);
#endif
