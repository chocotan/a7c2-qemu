# Bounded virtual optical frame owner

This caller-owned C11 component leases actual RGB pixels from the existing
[optical renderer](../virtual-optics/optics.c), supplies out-of-band generation
and readback metadata, and permits one active frame at a time. It uses no heap,
files, process-global state, locks, firmware inputs, or device-ready signals.
`Capture_verified=false`: native CP/SDK, guest DMA, SDS and Fsys remain unbound.

The scene is exactly the renderer's existing prototype: fixed 35 mm lens,
36 mm sensor-width assumption and checker targets at 1 m and 4 m. Configuration
copies `optics_params` by value; there is no second physics implementation or
scene-pointer lifetime to manage. F-numbers are exactly 4/8/16; focus is metres
(at least 0.1 m or positive infinity), shutter is seconds, ISO is finite and
positive. Parameter validation calls the existing renderer on a local 1×1 probe
before accepting configuration. `optical_frame_autofocus` performs bounded virtual
contrast AF using actual rendered RGB pixels in a caller-selected ROI and lens
range. It updates focus only after a successful scan; this is an explicit host
virtual AF result and supplies no native Sony AF ACK or ready state.

**AF API change:** the previous one-argument unsupported prototype is replaced by
`optical_frame_autofocus(owner, request, scratch, capacity, result)`. All existing
callers were confined to this directory and are updated together. The numeric
`OPTICAL_FRAME_UNSUPPORTED` value remains reserved for status-code compatibility but
is never returned by AF. Flat responses return `OPTICAL_FRAME_NO_CONTRAST`.

## Reproduce the host checks

From this directory, with a host C compiler, libm, pkg-config/libjpeg development
files, Python pytest and Pillow installed:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider test_owner.py -q
```

Observed result: **22 passed** (2026-10-27). The original seven C contract groups
remain, with three further AF groups; all ten run as both an optimized build and
an ASan/UBSan build. The original two encoder tests now run nine owned frames,
including defocus and near/far AF, through the existing JPEG engine and independent
Pillow decode. Both builds use
`-std=c11 -Wall -Wextra -Werror -pedantic`; the sanitizer build enables address,
undefined-behavior and leak diagnostics with fail-on-error. Builds are confined
to pytest's temporary directory. JPEG bytes travel through anonymous pipes and
`BytesIO`; no JPEG/MP4 photo is written to disk. These checks run no VM, network,
private/full-system assets, hardware or physical SD.

The first six JPEG frames use F4/focus 1 m, F8, focus 4 m, doubled shutter, doubled
ISO, and odd 1025×65 geometry. Three more start at 0.1 m: defocused, AF near ROI,
and AF far ROI. Pillow verifies RGB dimensions, decoded pixel error, exposure
response, the two-depth sharpness exchange, and actual post-AF sharpness: each
selected plane exceeds its defocused gradient by more than 5× plus 5, reaches at
least 95% of its manual-focus reference, and exceeds the opposite ROI's focused
frame by more than 2×. These conditions are checked on both raw and independently
decoded pixels. For **each** frame, the C process keeps its exact lease live while
Python fully decodes and checks the bytes; only then does Python send its
generation/hash reply over stdin, allowing the C test to retire that lease. This
is a test synchronization step, not an ACK API in the owner or evidence of
firmware consumption.

The first combined run reported **20 passed, 2 failed**, with both AF C builds
aborting (`returncode=-6`) at `after > 2 * roi_gradient(..., &other)` when the new
short-height fixture used width 512. The renderer scales blur by frame width;
512 did not separate the planes by that factor. The fixture now uses the existing
optics test width 1024 while retaining the 2× threshold. The combined rerun passed
all 22 tests in 4.63 s; the negative result is retained here rather than omitted.

## Use the owner

Include [optical-frame-owner.h](optical-frame-owner.h) and link
`optical-frame-owner.c`, `../virtual-optics/optics.c` and libm. The production owner
does not depend on the JPEG engine; only the integration tests link it.

```c
#include "optical-frame-owner.h"
#include <assert.h>

static int consume(const optical_frame_view *frame, void *context)
{
    (void)context;
    uint64_t hash = UINT64_C(14695981039346656037);
    for (size_t y = 0; y < frame->height; ++y)
        for (size_t x = 0; x < frame->width * 3; ++x)
            hash = (hash ^ frame->pixels[y * frame->stride + x]) *
                   UINT64_C(1099511628211);
    return hash != frame->metadata.pixel_fnv1a;
}

int main(void)
{
    optical_frame_owner owner = {0};
    optical_frame_config config = {{4, 1, 0.001, 100}, 3, 3, 11};
    optical_frame_lease lease;
    unsigned char pixels[33] = {0};
    assert(optical_frame_init(&owner) == OPTICAL_FRAME_OK);
    assert(optical_frame_configure(&owner, &config) == OPTICAL_FRAME_OK);
    assert(optical_frame_acquire(&owner, pixels, sizeof pixels, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_render(&owner, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_consumer_read(&owner, &lease, consume, NULL) == OPTICAL_FRAME_OK);
    assert(optical_frame_retire(&owner, &lease) == OPTICAL_FRAME_OK);
    return 0;
}
```

The caller externally serializes each owner, preserves its address, and never
copies, reinitializes or edits its private fields. Separate owners have no shared
state. A leased buffer remains alive, exclusively assigned to this owner and
unmodified until correct retirement; concurrent access is outside the contract.
The caller also supplies real readable/writable objects of the declared sizes.
Integer range checks reject wrapping addresses, but cannot prove that arbitrary
pointers are mapped or that a claimed allocation really exists.

| Operation | Required state | Effect |
| --- | --- | --- |
| `init` | Zero-initialized storage | Starts idle; repeat initialization is rejected |
| `configure` | Idle | Validates geometry and optics, then copies configuration |
| `acquire` | Configured, idle | Binds caller buffer/capacity, increments generation, stages token |
| `render` | Staged, matching token | Fills actual RGB and produces out-of-band metadata atomically |
| `consumer_read` | Rendered, matching token | Verifies active-byte hash, lends a synchronous const RGB view |
| `copy` | Rendered, matching token | Verifies hash, copies all active rows to a disjoint bounded destination |
| `retire` | Staged or rendered, matching token | Releases the lease without implied reading or encoding |
| `snapshot` | Initialized | Copies state, configuration, metadata and separate counters |
| `autofocus` | Configured, idle | Scans actual RGB contrast in ROI/range; commits focus only on success |

Generation starts at 1, never resets on reconfiguration, and fails closed at
`UINT64_MAX`; every counter also refuses to wrap. A token matches owner address,
generation, buffer address **and capacity**. Wrong/stale tokens, a second live
acquisition, reconfiguration during a live lease and duplicate retirement leave
the owner and buffers unchanged. Retirement does not zero pixels or alter tokens.

Both source and copy destination require `capacity >= stride * height`, including
last-row padding, to match the renderer's contract. Checked multiplication,
nonwrapping declared address spans, and disjoint owner/token/output/buffer spans
precede writes. Rendering and copying write only `width * 3` bytes per row and
preserve padding/canaries. Pixel identity is checked against direct existing
renderer output, including row 0; there is **no in-band frame-ID/checksum row**.

A borrowed view expires when its callback returns. Its format is explicitly
`OPTICAL_FRAME_VIRTUAL_RGB888`, with R/G/B bytes in top-to-bottom rows, and carries
geometry, full stride extent, generation and optical metadata. A successful
`copy` returns a view of caller-owned destination storage, whose lifetime the
caller controls. Neither view declares Sony YC/Bayer packing. `DataSiteIibNumber`
is an identifier and supplies no pixel-layout evidence. No SDS header is guessed.

`staged`, `rendered`, `read`, `copied` and `retired` are distinct counters.
`read` counts borrowed callback invocations after a complete source hash check,
including callbacks returning failure, plus successful full-frame copies.
`copied` counts those copies only. Callback return zero proves no particular
consumer read or codec success; the encoder test checks the encoder's own result
and actual independent decoded pixels. No counter is called AP consumed/encoded.
During a callback, mutating/reentrant owner operations are rejected; snapshots
remain available. Nonzero callback return yields `CONSUMER_FAILED`, and changed
active pixels yield `CHANGED` with the lease still live. Source hashes are checked
before read/copy and after borrowed callbacks; FNV-1a detects accidental changes,
not adversarial mutations or hash collisions. Caller immutability remains required.

## Focus a selected ROI

The request's `x`, `y`, `width`, `height` use configured full-frame pixel
coordinates. Width and height must each be at least 2, and the entire ROI must fit
without wraparound. `near_m` is finite and at least 0.1 metres; `far_m` is greater
than `near_m` and may be positive infinity. An unresolvable reciprocal range is
invalid. Scratch uses the configured full-frame stride and requires at least
`stride * height` bytes, including last-row padding. Owner, request, scratch and
result declared spans must all be disjoint; the caller supplies actual live
storage and serializes access. No heap, file or extra image plane is required.

This complete example focuses the left ROI, then reuses scratch as the ordinary
owned frame buffer. Link it with the owner, existing optics and `-lm`:

```c
#include "optical-frame-owner.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>

int main(void)
{
    optical_frame_owner owner = {0};
    optical_frame_config config = {{4, 0.1, 0.001, 100}, 1024, 16, 3085};
    optical_frame_af_request request = {16, 4, 480, 8, 0.1, INFINITY};
    optical_frame_af_result result;
    unsigned char scratch[3085 * 16];
    assert(optical_frame_init(&owner) == OPTICAL_FRAME_OK);
    assert(optical_frame_configure(&owner, &config) == OPTICAL_FRAME_OK);
    assert(optical_frame_autofocus(&owner, &request, scratch, sizeof scratch,
                                   &result) == OPTICAL_FRAME_OK);
    assert(fabs(result.focus_m - 1) < 0.08 && result.score > 0);
    assert(printf("focus=%.6f m score=%.6f samples=%zu+%zu\n", result.focus_m,
                  result.score, result.coarse_samples, result.refinement_samples) > 0);
    optical_frame_lease lease;
    assert(optical_frame_acquire(&owner, scratch, sizeof scratch, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_render(&owner, &lease) == OPTICAL_FRAME_OK);
    assert(optical_frame_retire(&owner, &lease) == OPTICAL_FRAME_OK);
    return 0;
}
```

Both complete C examples were compiled and executed with the same strict C11
warning flags. The AF example returned `focus=1.003922 m score=349.045838
samples=17+12` on the existing renderer.

Every candidate calls the unchanged `optics_render` for the full configured
geometry. Only actual ROI pixels are scored, using
`Y = (54*R + 183*G + 19*B)/256` and the mean of squared horizontal/vertical
luminance differences. The score is in squared 8-bit luminance units, 0–65025.
Seventeen coarse distances are uniform in diopters (`1/metres`, infinity → 0).
Six refinement rounds test the two half-step neighbours of the current best,
skipping candidates outside the requested range or numerically identical ones.
There are exactly 17 coarse renders and at most 12 refinement renders; returned
counts describe actual evaluations. The best sampled distance and score are
returned. Equal scores retain the first candidate. No target depth, blur radius
metadata or scene-depth oracle enters the search.

A zero best score or score spread no larger than `max(1e-9, best_score*1e-6)`
returns `NO_CONTRAST`. Tests cover clipped white, underexposed black, a constant
2×2 ROI within the textured scene, and positive but focus-invariant contrast.
All errors preserve owner and result. Argument/state validation also preserves
scratch; once a scan starts, active scratch pixels may change even on
`NO_CONTRAST`, but padding, guards and excess capacity never change. Success
changes only `config.params.focus_m` and the result: generation, counters,
metadata and the caller's original configuration/request remain unchanged.

Any active STAGED/RENDERED/READING lease causes `STATE` before a scratch write,
including reentrant AF from a borrowed callback. Retirement is still mandatory.
Scratch contains the final trial, which need not be the winning one; request an
ordinary acquire/render after success to obtain the focused frame. The bounded
local refinement is suitable for this existing checker scene; narrow or multiple
peaks from future scenes/lenses may require a denser scan. Neither this algorithm
nor its result is a claim of native Sony AF lock, timing or completion.

## Evidence, result and remaining binding

| Evidence | Validated result | Path / remaining boundary |
| --- | --- | --- |
| `test_owner.c`: lifecycle/configuration | Exact token retirement, generation advance, frozen live configuration, rejection of busy AF | `configure → acquire → render → retire`; no fake ready transition |
| `test_owner.c`: bounds/copies/exhaustion | Atomic rejection, declared-span overlap/overflow checks, row padding, counter wrap rejection | Caller storage → bounded RGB buffer/copy; allocation truth remains caller responsibility |
| `test_owner.c`: consumers/renderer-identity | Real active-byte readback, immutable source, no row watermark, reentrant mutation rejection | Existing `optics_render → borrowed view`; no Sony format claim |
| `test_owner.c`: autofocus | Starts defocused, chooses near/far ROI peaks from actual pixels, sharpens selected plane; restricted range chooses endpoint; preserves request/config/previous pixels and guarded scratch | `optics_render → ROI luminance gradients → bounded scan → focus commit`; virtual AF only |
| `test_owner.c`: autofocus-flat/autofocus-bounds | Flat/empty texture fails atomically; invalid ROI/range/stride/pointers/capacity/overlap rejected; active lease cannot be changed | Caller request/scratch → validated host AF; no focus/readiness promotion on failure |
| `test_owned_rgb_encoder_pillow_before_retire` | Nine real owned RGB frames, including post-AF near/far → existing JPEG encoder → independent Pillow image → exact lease retirement | Host data path only; no original firmware request/completion or storage claim |

This component does not implement CP `3003` or populate the four real state
fields of its 16-byte reply. Host RGB ownership and virtual AF do not establish
those fields or the still-unknown original source. Future integration must
establish the actual SDK/SDS/DMA lifetime, layout and consumer contract, then drive
the original completion and storage paths. The parent owns that integration and
the joint end-to-end VM check; this component runs no VM.

| Verification claim | Value |
| --- | --- |
| Original CP pipeline | false |
| Original SDK consumption | false |
| Sony packing / SDS binding | false |
| Guest DMA consumption | false |
| Original Fsys capture output | false |
| `Capture_verified` | false |
| JPEG/MP4 disk photos produced | false |

Only this new component directory is delivered here; existing runtime, optics,
JPEG, state providers and integration sources are unchanged.
