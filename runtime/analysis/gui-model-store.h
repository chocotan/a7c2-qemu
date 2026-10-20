#ifndef NATIVE_GUI_MODEL_STORE_H
#define NATIVE_GUI_MODEL_STORE_H
#include "gui-model-wire.h"

#define GUI_MODEL_STORE_PATH "/tmp/gui-model-state.bin"
#define GUI_MODEL_STORE_BASE_BYTES 860U
#define GUI_MODEL_STORE_PREFIX_BYTES 852U
#define GUI_MODEL_STORE_BYTES (GUI_MODEL_STORE_BASE_BYTES + 4096U)
struct gui_model_store {
    struct gui_model_batch current;
    unsigned long long packets, generations[GUI_MODEL_TYPES];
    unsigned int changed, failed;
};
struct gui_model_store_ops {
    int (*receive)(unsigned int, void **, long);
    unsigned int (*size)(void *);
    int (*release)(unsigned int, void *);
    int (*persist)(const char *, const unsigned char *, unsigned long);
    void (*log)(const char *, const char *);
    const unsigned int *stop;
};
/* Virtual AP snapshot store; not the original CP subscription/query protocol. */
int gui_model_store_step(struct gui_model_store *, const struct gui_model_store_ops *, const char *);
int gui_model_service_start(const struct gui_model_store_ops *);
/* 1 means this virtual endpoint handled the call; rc is transport acceptance only. */
int gui_model_service_send(unsigned int, void *, int *rc);
#endif
