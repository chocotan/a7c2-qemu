#include "gui-model-wire.h"
#include <string.h>

static unsigned int word(const unsigned char *p) {
    return (unsigned int)p[0] | (unsigned int)p[1] << 8 |
           (unsigned int)p[2] << 16 | (unsigned int)p[3] << 24;
}

int gui_model_decode(const void *message, size_t bytes, struct gui_model_batch *out) {
    static const unsigned int types[GUI_MODEL_TYPES] = {0x10, 0x15, 0x16, 0x19, 0x1a, 0x1b};
    static const unsigned int sizes[GUI_MODEL_TYPES] = {0x274, 0xc, 0x14, 0xc, 4, 0x10};
    if (!message || !out || bytes < 8 || bytes > 4096) return -1;
    const unsigned char *p = message;
    if (word(p) || word(p + 4) != bytes - 8) return -1;
    struct gui_model_batch batch = {0};
    unsigned int seen[64];
    size_t offset = 8;
    while (offset < bytes) {
        if (bytes - offset < 8) return -1;
        unsigned int type = word(p + offset), count = word(p + offset + 4), index;
        offset += 8;
        for (index = 0; index < GUI_MODEL_TYPES && types[index] != type; index++) {}
        if(count>bytes-offset || batch.records==64)return -1;
        for(unsigned int i=0;i<batch.records;i++)if(seen[i]==type)return -1;
        seen[batch.records++]=type;
        if(index<GUI_MODEL_TYPES && sizes[index]==count) {
            batch.present |= 1U << index;
            batch.values[index].type = type;
            batch.values[index].bytes = count;
            memcpy(batch.values[index].data, p + offset, count);
        }else batch.opaque++;
        offset += count;
    }
    *out = batch;
    return 0;
}
