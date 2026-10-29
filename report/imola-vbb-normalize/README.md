# Imola VBB owned numeric normalization

`nvbb_normalize_subrecord()` implements the source-closed numeric portion of the two ordinary VBB normalizers. It is a diagnostic transform of an owned byte buffer, usable later by a device frontend after that frontend has captured actual configuration values. A return of zero means only that numeric output bytes were derived. Pixel layout, format meanings, hardware backend field roles, and a direct CMOS producer remain unclosed; `native_gaps=63`, `native_capture=false`, and `capture_verified=false` remain unchanged.

This package contains one pure C API, six HOST_TEST scenarios, and four authenticated source windows totaling 604 bytes. It does not program registers, start an engine, send an ACK, generate an IRQ, consume a frame, produce encoded output, or assert engine completion. No system VM, MCU execution, physical device, private/full dump, dependency installation, or QEMU build is involved. The one ABI test runs the new C test program with an existing QEMU **user-mode** executable and original AArch64 libc; it does not execute the original MCU functions.

## Use an owned record

The public interface is declared in [vbb-normalize.h](vbb-normalize.h):

```c
int nvbb_normalize_subrecord(uint32_t base, uint8_t address_mode,
                             uint8_t auxiliary_mode, const unsigned char *src,
                             size_t src_bytes, unsigned char *out,
                             size_t out_bytes);
```

`NVBB_SUBRECORD_BYTES` is `0x4c` (76). The selected-work analysis identifies a `0x98` work area used in two halves; the pinned virtual-slot wrappers independently show the second-half `W+0x4c` addition. This establishes the adapter's copy envelope, not a pixel stride or a completely interpreted native structure.

A future caller must supply the actual captured `u32[C+0x18]`, `u8[C+0x1c]`, and `u8[C+0x1d]` as `base`, `address_mode`, and `auxiliary_mode`. The helper does not read a context pointer, infer defaults, or obtain configuration provenance for the caller. The source must be an owned, immutable byte buffer, not original CP memory or live MCU RAM. Merely copying bytes does not establish readiness or make their opaque fields logically known.

Both declared spans must be accessible throughout the call, at least `0x4c` bytes long, non-wrapping in `uintptr_t`, and entirely disjoint. Overlap checks include **all declared source bytes and all output capacity**, including unused tails. Byte pointers may be unaligned. Pointer arithmetic checks cannot prove that an address is mapped or backed by the claimed allocation; that remains the caller's responsibility.

On success the helper copies exactly `0x4c` bytes, replaces only the three little-endian words at offsets `0`, `4`, and `8`, preserves opaque bytes `0x0c..0x4b`, and leaves the output-capacity tail untouched. Source bytes and `errno` are preserved on every return. There is no heap allocation, persistent state, ownership flag, callback, generation counter, or batch API.

| Result | Condition | Output |
|---|---|---|
| `0` | Supported consumed modes and valid buffers | One numeric record derived |
| `-EINVAL` | Null pointer or overlapping declared spans | Entire output unchanged |
| `-EOVERFLOW` | Either declared span wraps | Entire output unchanged |
| `-EMSGSIZE` | Either size is below `0x4c` | Entire output unchanged |
| `-ENOTSUP` | Unsupported address mode, or unsupported auxiliary mode when word `+8` is nonzero | Entire output unchanged |

Validation order is null, span wrap, size, overlap, then modes. All arithmetic validation finishes before the one copy to output. This is an unchanged-on-error guarantee, not atomic publication to concurrent readers. No fields are committed if the auxiliary mode is rejected after the first two words have been computed locally.

Here is a complete laboratory example with a poisoned record and only twelve explicit numeric input bytes. These constants do not describe a hardware format or replace captured context values in a real caller.

```c
#include "vbb-normalize.h"
#include <assert.h>
#include <string.h>

int main(void)
{
    unsigned char src[NVBB_SUBRECORD_BYTES], out[NVBB_SUBRECORD_BYTES];
    const unsigned char numbers[12] = {3, 0, 0, 0, 0, 6, 0, 0, 9, 0, 0, 0};
    const unsigned char expected[12] = {2, 0, 0, 0, 0, 4, 0, 0, 4, 0, 0, 0};
    memset(src, 0xd3, sizeof(src));
    memcpy(src, numbers, sizeof(numbers));
    assert(nvbb_normalize_subrecord(0, 3, 2, src, sizeof(src), out, sizeof(out)) == 0);
    assert(memcmp(out, expected, sizeof(expected)) == 0);
    assert(memcmp(out + 12, src + 12, sizeof(src) - 12) == 0);
    return 0;
}
```

Two halves are handled by two independent calls with separately captured values. [test-vbb-normalize.c](test-vbb-normalize.c) demonstrates this composition with distinct modes and a full source immutability check. There is no implied transaction across the two calls.

## Numeric behavior and original failure paths

Let `x = (LE32(W+0) - base) mod 2^32` and independently `y = (LE32(W+4) - base) mod 2^32`. Apply the following transform to each. Underflow is intentional original unsigned subtraction, not an invalid host pointer.

| Numeric address mode | Transform of `x` or `y` |
|---|---|
| `0`, `1`, `9` | Unchanged after subtraction |
| `2` | Unsigned right shift by one |
| `3` | `((uint32_t)(((uint64_t)x * 0xaaaaaaab) >> 32)) & 0xfffffffe` |
| `4`, `5`, `d` | `(((x / 3) * 4 + 0x1ff) mod 2^32) & 0xfffffe00` |
| `6`, `7`, `f` | Left shift by one modulo `2^32` |
| All other byte values | Conservative adapter rejection |

These are numeric mode values, not named pixel formats. Their output units need not be byte addresses. There is no reinterpretation of preserved opaque words as known configuration.

For `z = LE32(W+8)`, zero is unchanged and **does not consume auxiliary mode**: every auxiliary byte value is accepted if the address mode is supported. For nonzero `z`, auxiliary `1` preserves it and auxiliary `2` performs an unsigned right shift by one. Every other auxiliary byte value is rejected.

The original first function modifies words `0` and `4` in place by subtracting `u32[C+0x18]` **before** checking the mode. An unsupported mode calls the assert/logger at `0x8000ae50` and returns if that call returns; there is no error code. The second function similarly asserts for an unsupported consumed auxiliary mode, after the first normalizer has already modified the record. The adapter deliberately rejects with `-ENOTSUP` and leaves the entire output unchanged. This conservative error policy is not a claim that the original firmware behaves transactionally.

## Source verification

The immutable public artifact is `runtime/analysis/menu-root/usr/codec/vcd_firmware_imola2.bin`, 10,934,476 bytes, SHA-256 `15e75a9732e2f9904ada1c919c631dac0da57e605ce3daa4c6fb2ebe98982b5b`. The existing [image.py](../imola-mcu-firmware-contract/image.py) is pinned unchanged and used through `load_image()` followed by bank-explicit `read_window()`. Only `ram0` is used: raw `[0x9000, 0x714000)`, linked `VA = 0x80000000 + raw`. This is a static authenticated file view, not an execution or loader-copy claim. A raw MCU image has no ELF/PE import or export table; the relevant external control-flow evidence here is the explicit assert call and selected-job call targets.

| Evidence | Linked half-open interval | Bytes | Finding |
|---|---|---:|---|
| E1: Complete normalizers | `0x801bfd98..0x801bff38` | 416 | F1: Both ordinary numeric functions are complete |
| E2: Address-mode jump table | `0x80216260..0x802162a0` | 64 | F2: Eleven supported numeric modes and default assert target |
| E3: Selected-job call binding | `0x801be400..0x801be42c` | 44 | F3: Context byte `+1c` then byte `+1d` feed the two calls, before `0x801bff38` |
| E4: Core virtual-slot wrappers | `0x801c2388..0x801c23d8` | 80 | F4: Slot `+18` receives `W` or `W+0x4c`; addition is in the second call's delay slot |

E1 contains all 320 bytes / 80 instructions of `0x801bfd98` and all 96 bytes / 24 instructions of `0x801bfed8`. Raw subtraction, unsigned multiply-high, shifts, alignment rounding, the complete switch table, assert paths, `jr $ra` delay slots, and the final branch delay slots were checked against the parent's complete two-function Kuna output (`RC=0` reported by the parent; empty diagnostics observed). Capstone 5.0.7 decoded every word of both functions as an ordinary MIPS32 instruction. The tests repeat complete decoding and reject any instruction outside the observed ordinary mnemonic set. This does not settle the ISA of the rest of the MCU image or authorize running a codec.

[source-pins.json](source-pins.json) records the full artifact hash, all four exact window hashes, the two independent full-function hashes and boundaries, the unchanged reader hash, and the original Kuna-output hash. The scratch Kuna file is provenance from the prepared research workspace, not a new dependency or copied processor/ISA implementation in this package.

The supported path is E1/E2 → F1/F2 → P1: derive three numeric words in an owned diagnostic copy; E3/E4 → F3/F4 → P2: a later frontend can call this helper for the selected half after it establishes actual input ownership and configuration provenance. Neither path closes the register-programming function, an engine payload, pixel format, start/ACK/IRQ behavior, or native capture. The [hardware frontier report](../imola-vbb-hardware-frontier/README.md) maintains the larger boundary separately.

## Verify the implementation

From the `2026-10-17-qemu-native-camera` directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest -p no:cacheprovider -q \
  report/imola-vbb-normalize/test_normalize.py
```

Result in the prepared workspace: **15 passed**, no skips. Twelve pytest cases run the six C scenarios once under strict C11 (`-Wall -Wextra -Werror -pedantic`) and once with AddressSanitizer plus UndefinedBehaviorSanitizer. One additional case runs all six scenarios from the same C `main` linked to the original AArch64 libc using the existing `lif-capability-owner/original-abi-entry.c`, `clang -nostdlib -fuse-ld=lld -mno-outline-atomics`, and prepared QEMU user-mode runner. Two cases authenticate source pins/control-flow words and decode the complete ordinary functions. Build products stay in pytest temporary directories.

The six scenarios check:

- `vectors`: 18 literal edge vectors × 11 modes × 3 bases = 594 calls, including base-relative zero/one, divide/alignment boundaries, `3*512` neighbors, `UINT32_MAX`, subtraction underflow, left-shift wrap, alignment wrap, and multiply-high results. Both first words have independent literal expectations.
- `matrix`: all `256*256` address/auxiliary pairs for both zero and nonzero word `+8` = 131,072 calls. Acceptance follows exactly `(address mode in the eleven-value set) && (z == 0 || auxiliary mode in {1,2})`; rejected calls preserve the entire output.
- `arguments`: nulls, zero/short sizes, wrapping source/output spans, both `SIZE_MAX` capacities, validation before dereference, and unsupported consumed modes. A nonzero auxiliary word with an unsupported auxiliary mode cannot commit the already computed first two words.
- `alias`: same-buffer and partial overlap, overlap only in declared tails in both directions, and exact declared-span adjacency in both directions.
- `unaligned`: all sixteen combinations of source/output offsets modulo four, with unchanged prefix, capacity tail, source, and opaque bytes.
- `composed`: two explicit `0x4c` calls with distinct modes and immutable poisoned `0x98` laboratory input.

Every C call checks preservation of `errno`. Successful calls check preserved opaque bytes and untouched tails; error paths check unchanged output and source. These finite test iterations are adapter tests, not native execution coverage. The original-libc case skips outside a prepared workspace without clang/QEMU user mode; the static full-decoder case skips without the already-installed optional Capstone. Artifact authentication and raw control-flow pin tests remain separate. No dependencies are installed by the tests.
