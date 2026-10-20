#ifndef NATIVE_GUI_MODEL_WIRE_H
#define NATIVE_GUI_MODEL_WIRE_H
#include <stddef.h>

#define GUI_MODEL_TYPES 6
#define GUI_MODEL_MAX_BYTES 0x274
#define GUI_MODEL_QUEUE 0x9088076bU

struct gui_model_value {
    unsigned int type, bytes;
    unsigned char data[GUI_MODEL_MAX_BYTES];
};
struct gui_model_batch {
    unsigned int present, records, opaque;
    struct gui_model_value values[GUI_MODEL_TYPES];
};

/* Validate all inline records; retain six named layouts plus the caller's complete packet. */
int gui_model_decode(const void *message, size_t bytes, struct gui_model_batch *out);
#endif
