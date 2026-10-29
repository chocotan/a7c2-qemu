# Finite owned LIF 5/6 cache admission

This directory implements the completed05 source contract as a caller-owned,
finite **virtual cache**. It consumes immutable received bytes, validates the
actual capability owner, calls the live bitmap decoder once, copies the whole RX
into caller-owned backing, and exposes copied command/field results with
stale-handle protection. The existing receive API keeps capabilities read-only;
`lif_cache_receive_with_handshake` also applies the existing conditional owned
handshake stores in that same receive transaction. Neither API executes original
CP cache code, publishes to a source worker, produces ACK/ready, or certifies
native capture.

The implementation is portable owned C11, uses no heap, and touches no system VM,
device, network, physical memory, private configuration, full-system dump, or SD card.
The existing decoder and capability/handshake implementations are unchanged.
The only retained pointer is the caller's accessible RX backing pointer.

## Build and reproduce

From the `2026-10-17-qemu-native-camera` directory:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  report/lif-cache-admission-contract/test_cache.py
```

The harness compiles with `-std=c11 -Wall -Wextra -Werror -pedantic`, runs 34
named host scenarios, repeats all scenarios with ASan/UBSan, and checks all 16
source windows. It uses the existing public CP and authenticated ALLLANG assets;
when those assets are absent, asset-dependent tests explicitly skip. Temporary
executables and the extracted public initial stage go to pytest's temporary
directory. No dependencies are added. The linker wrapper in the test file counts
calls and forwards every call to the real `cp_lif_bitmap_receive_decode`.

The public-stage fixture is consumed unchanged through
`cp_property_stage_consume`, then the actual capability API consumes fixed
commands 1/7/8/3d, an explicit initial-kind K store, and a real bitmap request.
The request's complete 25 bytes are passed to
`cp_lif_bitmap_observe_transport_consumed`. HOST_TEST RX fixtures then enter the
new cache. Separate K=1 and K=0 source-store paths provide second-command-empty
and all-fields-empty cases without fabricating a live bitmap owner. Combined
handshake cases use the same setup, explicitly reset the control flags, receive
command 9 into the pending body, and consume the actual event-9 prefix API to
establish state 3. A separate fresh setup omits the handshake reset event to
retain genuinely unknown state; it never overwrites a live owner's state.

The verified result is **37 passed**: 34 strict-build scenarios,
one complete ASan/UBSan replay, the 16-window source check, and all 34 same C
scenarios executed as AArch64 with firmware libc2.25 in QEMU user mode. The prior
33-check pipeline and its original-libc check are preserved, with four new
scenarios added to every behavior pass. The initial run
had 31 passes and one fixture failure: a single actual `ff` byte was declared
as a two-byte span, which overlapped an adjacent guard and correctly returned
`-EINVAL`; the test's expected `-EMSGSIZE` assertion aborted with return code
`-6`. The corrected negative fixture supplies an accessible two-byte `ff 19`
buffer. The implementation did not need a failure-path change.

The original-libc check reuses the existing capability package's minimal entry
and the same real decoder-forwarding wrapper. Every scenario requires rc0 and
its complete output marker. Inputs remain HOST_TEST, so this does not establish
native CP execution or start a system VM. The broader frozen batch is separate.

## Use the owner under one external lock

Read [lif-cache.h](lif-cache.h) for complete signatures. Hold the same external
lock over cache, its backing, the capability owner, the bitmap owner, both guards
and the immutable transport inputs throughout each operation. Guards describe
one coherent source transaction; they do not prove an original CP event.

1. Zero every byte of a fresh `lif_cache_owner`, supply a separate accessible
   writable pool of at least `0x220` bytes, and call `lif_cache_init`. The pool is
   a host allocation chosen by the caller. Init records PID/origin/sequence and
   backing capacity; record/history/epoch contents remain unknown.
2. Consume the named source `lif_cache_consume_reset_and_prime` event before
   receiving. This clears metadata and global receipts, establishes known-empty
   global 5/6 references, primes slot 0 / pool start, and leaves both epochs
   unknown. It never fills or clears backing bytes.
3. At the actual cycle source operation, call `lif_cache_consume_cycle_roll`
   with exactly one immutable actual source token byte. This preserves the
   current tuple as previous, then creates a known current token and known-empty
   5/6 references. Unknown previous history remains unknown. All 256 byte values
   are usable, including `0xff`; the token is not a boolean or a cache index.
4. For receive, supply the actual raw RX extent, the actual typed ingress token
   and both 32-bit metadata values. Pass a separate **exact-current** capability
   snapshot guard and a **strictly newer** mutation guard, with the same PID and
   origin across owners. Call `lif_cache_receive` to keep capabilities byte-for-byte
   unchanged, or `lif_cache_receive_with_handshake` with the mutable actual
   capability owner to commit cache and owned handshake together. The combined
   call advances cache, capability and bitmap sequences to the mutation guard.
5. Retain the returned `{slot, incarnation}` handle. Read APIs take an exact
   current cache guard and copy bytes into a `lif_cache_result`. Use
   `lif_cache_snapshot` for metadata and history; it contains no backing pointer.

The caller owns the backing for the owner's complete fixed lifecycle. Release it
only after externally retiring the entire owner and all users. There is no pool
rebind, owner clone, token-reinitialization, or cleanup API. Do not zero or memcpy
an initialized owner to reuse its identity. A named reset preserves the monotonic
64-bit incarnation counter; exhaustion refuses before calling the decoder.

### Admission and failure behavior

Both receive APIs use one private helper that first validates all spans,
alignment, complete pool and complete output-capacity aliases, output size,
initialization/prime state, incarnation availability, reserve planning and the
actual capability snapshot with the supplied exact-current guard.
Both commands 5 **and** 6 must be known supported, even if only one appears in
RX; Z must be known zero. This is an explicitly stronger subset than the source
per-command support check. There is no arbitrary support flag/readback argument.

Only then does the read-only API call **the actual live bitmap owner** via
`cp_lif_bitmap_receive_decode`, exactly once. The combined API instead calls the
real `lif_capabilities_receive_dynamic` exactly once; that function performs the
single real bitmap decode and conditionally commits the owned handshake. On its
success, the helper copies `mutable_cap->value.last_dynamic`: this is the owned
result just produced by that same real call, never a caller-supplied struct or
validated flag. Both public wrappers bind the helper's snapshot source to the
same capability owner; only the combined wrapper supplies its mutable pointer.
Admission uses the real snapshot API before mutation, with no private layout or
revision magic and no fallible snapshot call after the capability update.

The existing requirement that the latest configured generation equals a fully
consumed 25-byte request receipt remains in force. There is no clone or
reinitialization of the live bitmap owner, second decode, caller-supplied decoded
frame, or forged SNAPSHOT context. Calling the two older receive APIs in sequence
would decode the same transaction twice and fail its sequence guard; use the
combined entry point when both commits are needed.

After successful decoding, all remaining work is local copying and infallible
metadata commits. Every refusal leaves all three owners, pool, raw RX, guards,
ingress and full output capacity unchanged. Successful read-only admission never
changes the capability owner. Combined admission preserves the fixed receipt
and uses the existing handshake mapping: known state 3 advances to 4 when command
5 is present, then known state 4 advances to 5 when command 6 is present, in that
order regardless of wire order. Command 6 alone at state 3 does not advance it;
unknown state stays unknown. The cache's last-nonempty field projection still
follows actual wire order. These separate ordering rules model the documented
source subset and owned policy, not observed native execution; see the unchanged
[capability handshake contract](../lif-capability-owner/README.md). The original
cache/CP/event-delivery and worker-publication flags remain zero, with no `3003`
data or readiness claim. This local atomic policy is stronger than the source,
which primes/mutates a record and invalidates it on parser failure.

| Return | Meaning |
| --- | --- |
| `-ENODATA` | Uninitialized/unprimed owner, unknown support/Z/history/table, or missing consumed request receipt |
| `-EACCES` | Known unsupported command 5 or 6; or existing type-1 gate rejection |
| `-ENOTSUP` | Z=1, unsupported owner revision/command, or decoder subset boundary |
| `-ESTALE` | Stale read/mutation guard, evicted/reused handle, or fresh lookup opaque mismatch |
| `-EAGAIN` | Torn/nonquiescent/odd sequence, or configured/consumed bitmap mismatch |
| `-EINVAL` | Wrapped/misaligned span, prohibited alias, invalid guard or pool invariant |
| `-EMSGSIZE` | Inadequate output, non-one-byte roll input, RX extent/framing mismatch |
| `-ENOSPC` | Backing smaller than `0x220` at init; ring wrap itself is not ENOSPC |
| `-EOVERFLOW` | Incarnation exhaustion or checked reserve alignment overflow |
| `-EXDEV` | PID/origin mismatch, including inherited owner use after fork |
| `-ENOENT` | Known-empty history, absent top command or absent projected field |
| `-EBADMSG` | Existing decoder envelope/checksum/type/trailer refusal |

All APIs preserve `errno`. Full declared output capacity, including unused tail,
must be disjoint from inputs, guard, owner and **all** backing capacity. Only the
specified output object is written on success. Inputs must be genuinely
accessible and immutable: numeric span checks cannot establish OS accessibility.

## Source receive and storage facts

The source is the public CP file pinned in [source-pins.json](source-pins.json):
18,090,880 bytes, SHA-256
`f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`.
File-backed CP VA is `[0x108000, 0x1248b80)`, with VA = raw offset + `0x108000`.
The listed RAM addresses below are **not** file offsets or host addresses.

`405490..405e60` is the complete original receive span. `a47d90` copies the
actual whole ingress frame to a **separate RX data ring**, then records metadata
and parser references. A native metadata `.record` has stride **0x324**, not an
embedded frame buffer. The static pointer/count literals at `1101f84`/`1101f88`
are `0x1fc9f70` / `0x40`: 64 metadata records.

| Native ingress source | Native record destination | New adapter input/storage |
| --- | --- | --- |
| entry `+0x00` u16 actual RX length | record `+0x04` u16 | Actual `rx_size`, decoder-owned length |
| entry `+0x02` u8 token | record `+0x06` u8 | Mandatory `ingress.token` |
| entry `+0x04` u32 | record `+0x08` u32 | Mandatory `ingress.metadata8` |
| entry `+0x10` u32 | record `+0x10` u32 | Mandatory `ingress.metadata10` |
| entry `+0x0c` frame pointer | record `+0x00` data pointer / whole copy | Actual raw RX, copied to owned pool offset |
| frame byte 3 flags | received frame flags | `record.flags` |
| frame byte 4 opaque, record `+0x15` | Opaque lookup value | `record.opaque`, distinct from ingress token |

The source ingress base is RAM `19edfd0`, stride `0x14`. After copying, source
clears ingress fields and performs DMB. The adapter starts after transport has
already delivered immutable bytes and metadata; it does not invent an ingress
ring index, emulate a native descriptor, or claim that descriptor was admitted.
The caller must connect these mandatory values to its real virtual source;
HOST_TEST inputs remain HOST_TEST.

The native RX data split is **B+0x6a00 .. B+S**. Runtime B and S are unresolved.
Neither the fixture pool capacity nor the host pool pointer asserts either
native value. `a90200 -> 3e164c` establishes reserve `0x220`, stored at RAM
`19edfc8`. The owned model therefore caps the **whole actual RX extent** at
`0x220`, including an optional final zero. The unchanged decoder accepts up to
`0x220+1`; this adapter deliberately admits the stronger whole-reserve subset.
With the finite 39 fields, the largest schema-complete 5+6 logical frame is
363 bytes; the reserve remains a safety boundary rather than padding allowance.

### Reserve and eviction policy

Source `a47302` computes
`p = align_up(previous.data + previous.rx_length, 16)`, then uses p if
`p + 0x220 <= rx_end`, otherwise `rx_begin`. The adapter performs the equivalent
checked host-pointer/size calculation before decoding. The first post-prime
reserve starts exactly at caller pool begin. Every accepted frame advances the
actual metadata index modulo 64 and retains its complete actual length.

Source invalidation checks old **starts** in the overwritten reserve window.
The owned model conservatively invalidates any live old **frame span**
intersecting the new `0x220` reserve, plus the chosen metadata slot. This is a
local safe policy, not proof of the original allocator. Small pools naturally
wrap and evict; they do not stop merely because metadata or ring space was used.
Only actual received bytes are copied. Reserved padding and other pool bytes are
left untouched. Invalidated records retain diagnostic receipt metadata while
`live=0` makes their handles unusable. History may retain such a handle; lookup
returns `-ESTALE` rather than silently rebinding it to a reused slot.

## Shared field table and token/opaque history

The existing decoder's **union** of both command field groups is correct for
its decoded transport views and stays unchanged. Cache projection is separate.
Source `a924f4` restarts field index at zero for **each** dynamic command;
`a47466` writes the same record table and last dynamic index. The cache therefore
copies **only the last nonempty command's field prefix in wire order**.

| Actual wire order / selected fields | Owned top lookups | Owned shared field table |
| --- | --- | --- |
| 5 with id 0, then 6 with id 0x40 | Both commands available | Only command6 fields; id 0 returns `-ENOENT` |
| 6 with id 0x40, then 5 with id 0 | Both commands available | Only command5 fields; id 0x40 returns `-ENOENT` |
| Nonempty 5, then empty 6 | Both commands available | Command5 prefix persists |
| Empty 6, then nonempty 5 | Both commands available | Command5 prefix |
| Both commands have no selected fields | Both command bytes available | Table remains unknown; `-ENODATA` |

Each top reference contains its copied-frame offset/length including the command
byte, actual source metadata and original field count. The shared table has its
own bounded field refs and last index; there is no misleading decoder-union
`first_field` index in these top refs. All offsets are relative to the actual
copied RX and bounded by its length. Plain command and field lookups copy data,
so no borrowed input or cache pointer survives eviction.

Source `a4763c/a47670` always updates global last5/last6 for present top commands.
It updates the current tuple's corresponding slot only when the **actual ingress
token** equals the current epoch token. The owned tuples store incarnation-aware
handles. A matching frame token does not roll an epoch, and a mismatching token
still updates the global receipt without replacing current matching history.

Source `a90388 -> a47890` returns **opaque**, not ingress token. Worker command5
compares opaque to current byte `[1b1a7b0]` before field lookup. The command6
worker prefix reads opaque but does not show the same equality gate.
`lif_cache_lookup_current_field` deliberately requires a current matching-token
handle **and opaque equality for both commands**, so its command6 policy is more
conservative. Plain handle-based lookups remain available for diagnostic
mismatches. Field command ownership follows the actual shared table, so a table
last written by 6 cannot supply 5's fields.

## Evidence → finding → implementation path

These source pins establish static facts, not observed native execution. The ten
completed05 windows contain 7,262 bytes; six supplements contain 124 bytes;
all **16 / 7,386 bytes** are independently hashed by the local test. Source RAM
layout literals do not resolve live native allocation or runtime state.

| Evidence | Finding | Implementation / verification path |
| --- | --- | --- |
| `405490..405e60`, `a47ca8..a47e40`, `1101f84..1101fc4` | Whole RX is copied separately; 64 metadata records | `lif_cache_receive`, `copy`, `metadata-reuse` |
| `a471b4..a478c4`, `a90200..a90224`, `3e164c..3e1754`, `3e22bc..3e2394`, `deeb50..deeb6c` | Aligned wrap reserve; runtime B/S unknown | Checked reserve planner; span eviction; `byte-eviction`, `bad-rx` |
| `a9570a..a95732` | Named reset/prime is separate from construction | Explicit reset event, preserved pool/counter; `init`, `reset`, `reset-aba` |
| `a9028c..a907ba`, `a90f42..a90f46`, `a9902a..a99036` | Cached support precedes command lookup; Z is source-owned | Actual capability snapshot before real decode; support/Z refusal cases |
| `a923d0..a92590`, `a471b4..a478c4` | Dynamic writer restarts the same field prefix | Last-nonempty projection; `order5`, `order6`, all empty cases |
| `a90ec2..a90ece`, `a96cea..a96cee`, `a471b4..a478c4` | Source u8 cycle roll and token-conditioned current slots | One-byte roll API, global/current/previous tuple tests |
| `405084..405150`, `a9028c..a907ba` | Opaque lookup differs from ingress token; worker5 equality | Plain copied lookup plus stricter current lookup; `opaque`, `history` |
| Actual bitmap owner + authenticated public capability/stage pipeline | Owned receive uses a consumed live configuration | Wrapped call count, `bitmap-receipt`, `bitmap-config`, `dataflow` |
| Existing real capability dynamic receive and handshake mapping | One decode can supply both handshake and cache; state-store order and field-table order differ | `lif_cache_receive_with_handshake`; `combined-flow`, `combined-order`, `combined-failures`, `combined-unknown` |

The 34 host scenarios cover cold/prime/epoch knownness, both orders, empty
commands, full copies and poison preservation, both eviction mechanisms, reset
ABA, support/Z refusal before decode, missing/stale bitmap receipt, exact/torn
and foreign guards, full-capacity pool/output aliases, wrapped/misaligned spans,
incarnation overflow, malformed/oversize RX, fork refusal and the complete owned
dataflow. The four combined scenarios additionally cover real pending9/event9
state setup, both wire orders and single-command state progression, actual owned
readback/frame/field equality, matching history and copied command bodies,
last-nonempty projection, genuinely unknown state, full output-tail preservation,
capability overlap confined to the declared output tail, and unchanged three-owner
state on support/Z, oversize, guard, missing receipt, newer configuration and
checksum refusals. Failures before the decoder record zero calls; actual decoder
refusals record exactly one. Fault injections into private owner members are
explicitly HOST_TEST negative tests, never asserted source events.

## Delivery boundary

| Capability | Status |
| --- | --- |
| Actual immutable RX → one real live bitmap decode → copied frame cache | Implemented and host tested |
| Independent top 5/6 refs and source last-nonempty shared field projection | Implemented and host tested |
| Named prime/roll, token/opaque history, stale copied lookups | Implemented and host tested |
| Capability/handshake owner mutation by this adapter | Optional combined API commits conditional owned handshake; existing read-only API remains byte-identical |
| Original CP cache/descriptor execution or worker publication | Unverified / not executed |
| Live native ring B/S, RTOS queue, DMA or original history | Unknown |
| ACK, CP ready, native capture/recording | No claim; report flags remain zero |

This delivery consists only of `lif-cache.c`, `lif-cache.h`, `test-lif-cache.c`,
`test_cache.py`, `README.md`, and `source-pins.json`. It creates no runtime hook,
GUI, generic event/allocator framework, source publisher or readiness sentinel.
