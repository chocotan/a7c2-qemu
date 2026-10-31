/* SPDX-License-Identifier: MIT */
#ifndef READONLY_SCOPE_TEST_GLIB_H
#define READONLY_SCOPE_TEST_GLIB_H
/* Only GLib's used surface is mocked; qemu-plugin.h is the real API 7 header. */
#include <stdbool.h>
#include <stddef.h>
typedef unsigned int guint;
typedef struct { char *data; guint len; } GArray;
typedef struct { unsigned char *data; guint len; size_t capacity; } GByteArray;
typedef struct { bool locked; } GMutex;
#define g_array_index(array, type, index) (((type *)(void *)(array)->data)[index])
void g_mutex_lock(GMutex *mutex);
void g_mutex_unlock(GMutex *mutex);
void g_array_unref(GArray *array);
GByteArray *g_byte_array_sized_new(guint reserved_size);
GByteArray *g_byte_array_set_size(GByteArray *array, guint length);
void g_byte_array_unref(GByteArray *array);
#endif
