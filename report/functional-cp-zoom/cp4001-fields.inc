/* Derived from public CP354768; same struct field/decode engine as cp-parameter-state.c.
 * Four independent unsigned-byte inputs; no clamp, sign extension or bitfields.
 * Descriptor-only handoff: main owns integration and joint validation. */
{0x9,0x698,1,1,COPY,0,UINT32_C(0x0)}, /* zoom_speed */
{0x8,0x69c,4,1,COPY,0,UINT32_C(0x0)}, /* zoom_drive */
{0xa,0x6a0,4,1,COPY,0,UINT32_C(0x0)}, /* zoom_trigger */
{0xb,0x6a4,1,1,COPY,0,UINT32_C(0x0)}, /* zoom_speed_movie_rec */
