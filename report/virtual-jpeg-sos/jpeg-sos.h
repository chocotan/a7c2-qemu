#ifndef VIRTUAL_JPEG_SOS_H
#define VIRTUAL_JPEG_SOS_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

enum jpeg_sos_status { JPEG_SOS_OK = 0, JPEG_SOS_REJECTED };

struct jpeg_sos_view {
    enum jpeg_sos_status status;
    const uint8_t *data;
    size_t offset;
    size_t length;
};

/*
 * Borrow FF DA..final FF D9 from a trusted host-engine complete JPEG only
 * when its baseline coding controls exactly match reference_prefix.
 * reference_prefix is caller-supplied SOI..immediately-before-SOS, not a JPEG
 * with entropy, an SOS marker, or a fabricated default. APPn/COM are ignored.
 * Both spans must be actual readable objects of their declared sizes, stable
 * throughout the call. They may overlap; neither is modified. Address wrap is
 * rejected, but C cannot establish object validity or reference provenance.
 * On success data == candidate + offset, length == candidate_size - offset;
 * the caller must keep candidate alive and unchanged while using the view.
 * Every failure returns REJECTED, NULL data, zero offset and zero length.
 * No allocation, copying of JPEG bytes, external I/O, decode proof, guest DMA,
 * interrupt, device-ready, source-equivalence, or capture semantics.
 */
struct jpeg_sos_view jpeg_sos_suffix(
    const uint8_t *candidate, size_t candidate_size,
    const uint8_t *reference_prefix, size_t reference_size);

#ifdef __cplusplus
}
#endif

#endif
