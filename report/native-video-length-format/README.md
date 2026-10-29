# Validate normal AU bytes against the declared container format

`nlength_validate()` reads the actual complete normal AU from the existing resolver's one/two borrowed ES spans and validates repeated **BE32(length) + NAL**. It returns the actual NAL count only after exact whole-AU validation. The new positive configuration staging evidence closes the **expected container format** for semantic `avc1` / `hvc1`: `lengthSizeMinusOne = 3`, hence four-byte big-endian lengths. **The original encoder producer and lifecycle remain unclosed; `native_capture = false`, `NVIDEO_NATIVE_GAPS = 63`.** This is a concrete consumer of provided bytes, not evidence of a configured real run or a native encoder producing valid bytes.

Scope and authorization: the delegated task permits these six new files only, public ALLLANG `usr/lib/libmpr.so` verification, and local HOST_TEST executables and memory fixtures. Existing binding, AU, parameter-set and frozen batch/observer files remain unchanged. No VM, network, hardware, physical SD, private/full-system source, native ACK/reply, PI push, lease free or capture is involved. Formal report flavor is null. This README contains the scope and timeline because the authorized deliverables are exactly six files; integration and the joint full batch belong to the parent.

## Call the single validation API

The interface is [native-lengths.h](native-lengths.h), implemented in [native-lengths.c](native-lengths.c):

```c
int nlength_validate(const uint8_t *info96, size_t info_size,
    uint64_t address_correction, uint64_t es_base,
    const uint8_t *es, size_t es_capacity, uint32_t container_type,
    size_t *out_count);
```

Supply exactly 96 immutable accessible descriptor bytes, the explicitly known original context+`0x40` correction, and the contiguous host mapping of the **whole** ES ring. Zero correction is accepted when explicitly known. The implementation invokes the actual [nau_resolve()](../native-video-au-contract/native-au.h), so corrected addresses, arithmetic, supported normal types `{0,1,2,3,9}` and ordered ring spans have one implementation. Type 4 remains the separate [parameter-set contract](../native-video-paramsets/native-paramsets.h). This raw-argument interface never accepts an externally fabricated `struct nau`, duplicate derived fields, a ready flag or a trust boolean.

`container_type` is the explicit semantic FOURCC `NLENGTH_AVC1 = 0x61766331` or `NLENGTH_HVC1 = 0x68766331`. The unknown request codec at PayloadMpr+`0x18` is not this value. The format is explicit; the implementation does not guess it from bytes. For example, `00 00 00 01 65` is a valid BE32 length-one AVC sample even though the same bytes can be described as an Annex-B start code. No automatic format-detection claim follows from acceptance or rejection.

This complete C11 example validates two NALs whose first length word crosses the ring end. Compile from this directory with the same source list and section garbage collection as [test_lengths.py](test_lengths.py).

```c
#include "native-lengths.h"
#include <assert.h>

int main(void)
{
    const uint8_t es[16] = {
        [0] = 0, [1] = 1, [2] = 0x67,
        [3] = 0, [4] = 0, [5] = 0, [6] = 1, [7] = 0x68,
        [14] = 0, [15] = 0
    };
    const uint8_t info[96] = {
        [0] = 1, [8] = 0x0e, [9] = 0x10, [0x10] = 10
    };
    size_t count = 99;
    int rc = nlength_validate(info, sizeof(info), 0x1000, 0x2000,
        es, sizeof(es), NLENGTH_AVC1, &count);
    assert(rc == 0 && count == 2);
    return 0;
}
```

The descriptor declares raw address `0x100e`; correction gives `0x200e`. The AU is ring bytes 14,15 then 0 through 7. Every prefix and body byte is read in source order, with no heap allocation, concatenation, generated prefix or copied AU. The byte reader uses volatile loads so reads of uninterpreted body bytes cannot be optimized away. This does not provide synchronization or prove the storage is mapped.

## Exact validation and caller responsibilities

Each four-byte unsigned big-endian length must be nonzero and fit the remaining AU bytes. Bounds use subtraction rather than overflowing `length + prefix` arithmetic. A NAL count cannot overflow `size_t`: each counted NAL consumes at least five bytes of the resolved, bounded AU. Length words, either header byte and arbitrary bodies can split at the ES wrap. No trailing byte is discarded, including descriptor padding metadata or one to three bytes after the final valid NAL.

AVC requires a minimum one-byte header with `forbidden_zero_bit == 0`. There is no NAL-type restriction, including for type zero or reserved types. HEVC requires at least two bytes, `forbidden_zero_bit == 0` and the second header byte's low three bits (`temporal_id_plus1`) nonzero; any layer ID is allowed. These are **adapter header checks**, following the separate type-4 adapter's basic header rules, not evidence that the original normal-AU parser checked them. The production code does not decode RBSPs, infer keyframes, parse SPS dependencies, filter VCLs or parameter sets, or decode/convert Annex-B. SPS, PPS, VPS, SEI, AUD and other NALs count exactly as supplied. HEVC tests check these static rules and make no full HEVC decoding claim.

`out_count` is one aligned, accessible `size_t`, disjoint from all 96 descriptor bytes and the **entire** declared ES mapping, including unused capacity and either ring span. Inputs may overlap each other. There is no output-capacity parameter or caller-supplied view to validate; only `sizeof(size_t)` output bytes exist in this contract. Every failure leaves output bytes unchanged, including failures after valid earlier NALs. Success writes only the count. `errno` stays unchanged on every path.

| Return | Meaning |
|---|---|
| `0` | Every supplied AU byte belongs to a complete valid length/NAL sequence; count committed |
| `-EINVAL` | Null/alignment/alias error, zero NAL length, invalid adapter header, zero AU or invalid resolver argument |
| `-ENODATA` | Descriptor shorter than 96 bytes, incomplete length word or truncated NAL body |
| `-ENOTSUP` | Container outside semantic `avc1`/`hvc1`, or non-normal descriptor type including 4 |
| `-EOVERFLOW` | Host pointer or logical address arithmetic wraps |
| `-ERANGE` | Corrected AU start outside ES, or AU longer than capacity |

Resolver errors propagate unchanged; if multiple arguments are invalid, the first implemented check determines the return code. Numerical range checks cannot prove accessibility, authentic source ownership, immutability or a live lease. The caller keeps descriptor and mapping stable and live throughout the synchronous call and externally serializes mutation and retirement. Composition of resolver and validator adds no native authorization, lifetime management or publication. There are no callbacks, ACKs/replies, read-index/PI updates, native completion or Fsys file-written claims.

## Source declaration closed by actual staging copy

[source-pins.json](source-pins.json) records the public ELF identity: **3,528,576 bytes**, SHA-256 `4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`. VA equals file offset in first PT_LOAD `[0,0x2e4534)`. The second PT_LOAD has VA `0x2f53a8`, file offset `0x2e53a8`, file size `0x77c88`; GOT VA `0x2fd3c8` therefore maps to file `0x2ed3c8`. The manifest reuses the frozen [AU source pins](../native-video-au-contract/source-pins.json) by exact manifest hash and identical artifact identity. All **14 old windows / 1,652 bytes** are verified, with no duplicated windows or altered old conclusions. Eleven new positive windows total **696 bytes**: the nine supplied staging/callback windows plus the two bounded factory call windows needed to tie the default callback table to MPR context creation. No further factory exploration was performed.

The earlier AU report's stored-to-staged uncertainty is superseded for this declared-format finding by the new copy and relocation evidence here. Its original producer uncertainty remains. The source path is:

1. Record attributes store `3`: AVC M`220970..78` sets external+`4`; HEVC M`220b1c..20` sets external+`0x1d`. Setters M`20ac08` / M`20aee8` copy those fields to stored `C` and retain `C` in SampleDesc+`0x48` / +`0x58`.
2. Stager M`210010` validates the input description for AVC type `2` / HEVC type `0xb`. M`2100a0` loads the pair at Desc+`0x40` so `x28 = Desc+0x48 = C_AVC`; M`2100a8` loads Desc+`0x50` so `x27 = Desc+0x58 = C_HEVC`.
3. M`2101f8..238` allocates a `0x48`-byte AVC staging record `S`, passes `x2=C`, `x3=S` to M`20da50`, and stores `S` at boxrec+`0x50`. M`210240..280` allocates `0x38` bytes for HEVC, calls M`20e194` with its `C`, and retains `S` at boxrec+`0x60`.
4. M`20da84..daa0` explicitly selects destination `S+8`, source `C`, destination/source lengths `0x40`, then calls M`1d9e80`. HEVC M`20e1c8..e1e4` does the same with `0x30`. This is an actual copy path; no displacement is inferred from an apparent offset difference.
5. M`1d9e80` loads the callback at context+`0x58`, userdata at context+`0`, then branches to it. Default table builder M`21fe3c`, in pinned M`21feb4..bc`, loads GOT VA `0x2fd3c8` and stores the function at table+`0x58`. ELF `.rela.dyn` binds that slot with **R_AARCH64_GLOB_DAT (1025)** to `_Z14ff4_mpr_memcpyPvS_mPKvm`, defined at M`21e8a4`, size `0x14`, addend zero. Tests use existing pyelftools to verify the relocation and defined symbol; raw unrelocated GOT bytes are not treated as the callback target.
6. Actual `ff4_mpr_memcpy`, M`21e8a4..b8`, compares `x2,x4`, sets `x0=x1`, selects their minimum into `x2`, sets `x1=x3`, and branches to memcpy PLT M`7b3b0`. Thus the default path really copies `C+4 -> S+0xc` and `C+0x1d -> S+0x25`.
7. Default context constructor M`1c3aa0..3b34` allocates and zeros `0x98` bytes, copies `0x70` bytes from the callback table through the same table+`0x58` callback, and retains the function at context+`0x58`. Factory windows M`225378..53d4` and M`226a34..68` establish default-table construction before context creation. This is static default-path evidence; it does not assert that an arbitrary overridden callback or an observed real run used this table.
8. Parent writer M`20fd24` uses boxrec+`0x50` / +`0x60`; wrappers M`20daf4` / M`20e238` pass the whole `S` to M`20d768` / M`20de4c`. AVC reads `S+0xc`, ORs `0xfc`, and writes avcC payload byte 4; HEVC reads `S+0x25`, masks `3`, and writes hvcC payload byte 21. Literal box tags are `0x61766343` / `0x68766343`. The low two bits are `3`, closing the standard `avc1` / `hvc1` expected four-byte length declaration.

Original normal-AU transport (`MakeVideoEsList` M`11b958` through the copy path M`2b1500`) preserves all payload bytes; it does not rewrite NAL framing at that boundary. Neither this fact nor the configuration declaration proves the original encoder supplied a correct BE32 sample. The validator establishes that property only for the actual input bytes it successfully reads.

## Evidence, findings and path

All binary evidence references the public artifact/hash above; exact window hashes and file coordinates are in the manifest. Reproduce source evidence with the pytest command below, selecting `-k 'pins or relocation'` when only provenance is needed. HOST_TEST evidence has no persistent coded-file artifact: fixtures and decoded outputs are pipes/memory, so their content-hash field is n/a.

| Evidence IDs / source reference | Observation | Finding, location, confidence, status |
|---|---|---|
| Prior `E-avc-config-entry`, `E-hevc-config-value`, `E-avc-stored-copy`, `E-hevc-stored-copy`; new `E-stored-descriptors`, `E-stage-type-gate`, `E-stage-allocation` | Stored configuration fields and selected `C` reach the matching staged constructor | F1, `severity=n/a_re`, staging M`210010`, high, validated static path |
| New `E-avc-stage-copy`, `E-hevc-stage-copy`, `E-copy-dispatch`, `E-default-table`, `E-default-memcpy`, `E-default-context`, both factory pins; ELF relocation record | Default callback is actual bounded memcpy; explicit destination is `S+8` | F2, `severity=n/a_re`, M`20da84` / M`20e1c8`, high, validated static default path; real-run selection unobserved |
| Prior `E-avc-serializer`, `E-hevc-serializer`, `E-avc-array-writer`, `E-hevc-array-writer`; F1/F2 evidence | `3` reaches avcC/hvcC lengthSizeMinusOne fields | F3, `severity=n/a_re`, expected container declaration, high, validated; original producer unclosed |
| Prior `E-au-list`, `E-ring`, `E-copy-call`, `E-copy-list`, `E-copy-memcpy`; `test_strict_lengths`, `test_real_avc_coded_bytes_preserved` | Whole spans are consumed without payload rewriting; actual successful HOST_TEST samples have exact BE32 framing | F4, `severity=n/a_re`, `nlength_validate`, high, validated consumer; no native provenance/authentication claim |

P1 (`path_type=callflow`): record-attribute fixed fields [prior configuration pins, F1] -> stored `C` in SampleDesc [prior setter pins, `E-stored-descriptors`, F1] -> allocated `S`, explicit `C -> S+8` callback copy [`E-stage-allocation`, stage-copy/default callback/factory pins, F2] -> staged avcC/hvcC serializers [prior serializer/writer pins, F3] -> explicit four-byte expected-format consumer using real `nau_resolve()` [HOST_TEST, F4]. Residual risks: original encoder producer, real-run callback/configuration selection, native ownership/completion/publication and storage completion remain open. Pure reconstruction has no vulnerability severity, remediation, IOC or ATT&CK claim.

## Reproduce the scoped checks

From the native-camera result root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/native-video-length-format/test_lengths.py -q --tb=short --color=no
```

Final scoped result: **20 passed**. Eight C self-check modes run in both strict C11 and ASAN/UBSAN (16 cases); the real H.264 fixture check runs in both builds (two cases); two cases verify new pins/actual relocation and every frozen prior pin. Builds use `-std=c11 -Wall -Wextra -Werror -pedantic`, real `native-au.c` and `native-video.c`, section garbage collection, and no parser mock. Existing `cc`, pytest, pyelftools and ffmpeg/libx264 are used with no added dependencies. Executables are written only to pytest temporary directories.

Checks cover AVC parameter sets/SEI/AUD/reserved types, forbidden headers, HEVC minimum header/temporal-ID/layer rules, all positions in the fixed multi-NAL fixture where a ring wrap can split prefix or body, explicit tails 1/2/3/4, a nontrivial BE32 `0x101` length, exact ring-end and full-capacity AUs, zero/truncated/oversized lengths, `UINT32_MAX` declarations without allocating them, trailing bytes and invalid later NALs, unknown container/type 4, null/alignment/host/logical pointer wrap, whole-capacity aliases including unused tail and partial intersections, descriptor aliases, adjacent outputs, allowed input overlap, output-tail preservation, all supported normal types, zero explicit correction, immutable source snapshots, every error's output preservation and `errno`, and gap mask 63. Synthetic overflow pointers are rejected arithmetically before dereference; no test asks the validator to read unmapped memory. Foreign resolved views are excluded by the raw-argument API rather than accepted and revalidated as a second view framework.

The real AVC test generates one coded AU **in host memory only**, splits Annex-B **only inside the test helper**, and supplies BE32+original-NAL bytes to the production validator. The test reconstructs the NAL sequence independently and compares every coded byte in order, validates contiguous and wrapped mappings, then independently decodes both original and test-only Annex-B reconstruction with `ffmpeg -xerror ... -f null -`. This is a decoder/fixture baseline; it is not host capture, a native producer, native MPR file writing or callback/frame completion evidence. HEVC is covered by static header fixtures only.

Timeline: read project/AU/parameter-set contracts -> verify nine supplied windows, two bounded factory windows and actual ELF binding -> publish raw-argument API and byte-reading validator -> add strict C11/sanitizer boundary checks and memory-only AVC fixture -> pass all 20 scoped cases -> finish these six files for parent integration. No full regression, VM, real-run original encoder test or end-to-end capture was performed.
