/* SPDX-License-Identifier: MIT */
#ifndef FULL_REMOTE_STATE_H
#define FULL_REMOTE_STATE_H
#define REMOTE_STATE_SID 0x92b4086fu
#define REMOTE_STATE_WIRE_BYTES 1504u
#define REMOTE_STATE_BYTES 1488u
struct remote_state {
    unsigned int control_seen,control_command,snapshot_seen;
    unsigned long long requests,generation;
    unsigned char bytes[REMOTE_STATE_BYTES];
    unsigned int gps_init_seen,gps_seen,gps_source;
    unsigned long long gps_generation;
    unsigned char gps_configuration[36];
    unsigned char gps_bytes[1432];
};
int remote_state_apply(struct remote_state *,const void *,unsigned int);
int full_remote_state_dispatch(unsigned int,void *,unsigned int,unsigned int,
    int (*)(unsigned int,void *),void (*)(const char *,const char *));
#endif
