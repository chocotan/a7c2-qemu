/* SPDX-License-Identifier: MIT */
#ifndef FULL_GUI_MODELS_H
#define FULL_GUI_MODELS_H
#define GUI_MODEL_FIRST 0x10u
#define GUI_MODEL_COUNT 14u
#define GUI_MODEL_MAX_BYTES 628u
#define GUI_MODEL_BATCH_MAX 932u
struct gui_model_value {
    unsigned int size;
    unsigned long long generation;
    unsigned char bytes[GUI_MODEL_MAX_BYTES];
};
struct gui_model_history {
    unsigned int initialized;
    unsigned short version;
    unsigned int changes[32][2];
    unsigned char bytes[32][GUI_MODEL_MAX_BYTES];
};
struct gui_model_state {
    unsigned long long batches;
    struct gui_model_value values[GUI_MODEL_COUNT];
    /* Six independently checked CP setters. Version advances on every setter,
     * separately from the complete-payload comparison and local generation.
     * order: AFWindow, Aperture, ShutterSpeed, RemoteTracking, TCUB, RemoteAF */
    struct gui_model_history history[6];
};
/* Validate completely before mutation. Returns a changed-slot bit mask, or -1.
 * These are local observation generations, not invented CP version numbers. */
int gui_models_apply(struct gui_model_state *, const void *, unsigned int);
/* Intercept only this explicit virtual model-consumer profile. No ACK/ready.
 * Ownership: on success release once; on rejection sender retains the request. */
int full_gui_models_dispatch(unsigned int, void *, unsigned int,
    int (*release)(unsigned int,void *), void (*record)(const char *,const char *));
#endif
