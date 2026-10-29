/* SPDX-License-Identifier: MIT */
#include "rc-identity.h"
#include <string.h>

static int valid(const struct rc_identity_image *image)
{
    if (!image || image->format || !image->width || image->width > 8192 ||
        !image->height || image->height > 8192 || image->stride < image->width * 2u)
        return 0;
    return (uint64_t)(image->height - 1) * image->stride + image->width * 2u <= image->capacity;
}

int rc_identity_copy(const struct rc_identity_image *input, const void *source,
                     const struct rc_identity_image *output, void *destination)
{
    if (!valid(input) || !valid(output) || !source || !destination ||
        input->width != output->width || input->height != output->height ||
        input->phase != output->phase || input->type != output->type)
        return -1;
    size_t input_bytes = (size_t)(input->height - 1) * input->stride + input->width * 2u;
    size_t output_bytes = (size_t)(output->height - 1) * output->stride + output->width * 2u;
    uintptr_t src = (uintptr_t)source, dst = (uintptr_t)destination;
    if (input_bytes > UINTPTR_MAX - src || output_bytes > UINTPTR_MAX - dst)
        return -1;
    if (src == dst && input->stride == output->stride)
        return 0;
    if (src < dst + output_bytes && dst < src + input_bytes)
        return -1; /* Overlapping row layouts need a separate, evidenced contract. */
    for (uint32_t y = 0; y < input->height; y++)
        memcpy((unsigned char *)destination + (size_t)y * output->stride,
               (const unsigned char *)source + (size_t)y * input->stride, input->width * 2u);
    return 0;
}
