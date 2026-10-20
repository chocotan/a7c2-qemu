/* SPDX-License-Identifier: MIT */
#ifndef NATIVE_STILLCA_STATE_H
#define NATIVE_STILLCA_STATE_H
struct stillca_state {
    unsigned long object;
    unsigned int slot0,slot1;
    unsigned char initialized,completion0,completion1,initial_arrived;
};
/* Read-only, two equal reads; caller must confirm the original wait/run frames. */
int read_stillca_state(void *,unsigned long,unsigned long,struct stillca_state *);
#endif
