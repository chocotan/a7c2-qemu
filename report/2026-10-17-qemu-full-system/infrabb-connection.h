/* SPDX-License-Identifier: MIT */
#ifndef INFRABB_CONNECTION_H
#define INFRABB_CONNECTION_H
#include "scalar-connection.h"
#include "vef-bb-post.h"
int full_infrabb_connection_dispatch(unsigned int,void *,const struct full_imaging_io *,int,int *);
int full_infrabb_connection_release(unsigned int,void *,int (*)(unsigned int,void *),void (*)(const char *,const char *),int *);
void full_infrabb_connection_snapshot(struct scalar_connection_snapshot *);
void full_infrabb_post_snapshot(struct post_report *);
#ifdef FULL_PIN_CONNECTION_TEST
void full_infrabb_connection_test_reset(void);
#endif
#endif
