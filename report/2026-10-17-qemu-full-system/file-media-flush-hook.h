/* SPDX-License-Identifier: MIT */
#ifndef FULL_FILE_MEDIA_FLUSH_H
#define FULL_FILE_MEDIA_FLUSH_H
void full_file_media_before_send(unsigned int,void *(*)(void *,const char *),
                                 void (*)(const char *,const char *));
#endif
