# CP3003/3000 start-state data owner

This module derives the four CP3003/3000 data bytes from explicitly consumed source inputs. It implements the collector's tuple/flags/action/override updates and the separate fourth-byte getter, with atomic failures and process/coherence guards. The positive fixtures are **host-only source-input fixtures**; they do not establish native CP initialization, a live virtual LIF producer, publication, AP application, or camera readiness. Construction has zero known input bits and zero known output bits.

## Scope and reproduction

The delegated scope is the public ALLLANG CP image and six new files: the C owner/header, its C/Python tests, this README and [source-pins.json](source-pins.json). Authorization is the project's offline owner-authorized firmware research agreement and the delegated implementation request. Network, private/full-system assets, hardware, physical SD, VM execution, existing-file changes, the 76-getter snapshot and runtime integration are outside this worker's scope. This inline scope is the scope record for this bounded deliverable; no additional case files are created.

From the `2026-10-17-qemu-native-camera` directory:

```bash
python3 -m pytest runtime/analysis/test_cp_start_state_data.py -q
```

The tests compile strict C11 with `-Wall -Wextra -Werror -pedantic` and ASan/UBSan, run the host matrix, check the exported API, and verify 42 source windows (5,188 bytes, including overlapping windows). Source verification requires `runtime/analysis/menu-root/cp/cpapp-b.bin`; only that check skips when public assets are absent. C tests need no firmware or device. Both checks passed locally with the public image present.

## Integrating actual source data

The API is [cp-start-state-data.h](../../runtime/analysis/device-models/cp-start-state-data.h); the implementation is [cp-start-state-data.c](../../runtime/analysis/device-models/cp-start-state-data.c). No build/runtime file is modified here.

1. Initialize caller-owned storage with `cp_start_state_data_init`. This binds the current PID. Only the three immutable cache initializer bytes are seeded internally; they are not available reply data yet.
2. Hold the external source/owner lock. Supply a guard containing the current owner PID, matching even before/after source sequences, `quiescent=1` and the actual source origin. Use `VIRTUAL_SOURCE` only for a real virtual producer; `HOST_TEST` remains visibly distinct. Once consumed, an owner cannot change origins or processes. The guard is a caller contract, not an internal mutex or proof that native CP ran.
3. Consume one bounded raw LIF snapshot, override-bank pointee and, for override mode 1, the merge bank. All six source fields and both selected merge fields must be known. Supply explicit previous tuple/flags readback with `EVENT_HISTORY` when needed; this event sets no result-ready bits.
4. Consume actual property `01250006` payloads and bounded ADJ writes. For the computed fourth-byte branches, consume the actual current predicate-kind byte or Q copy/clear event as applicable. Profile 2, M=0 and an empty repository are never selected as defaults.
5. Consume `EVENT_FOURTH_READ` to execute the source getter. This models the M=2 cache writeback at getter time. Property, ADJ, kind and Q events invalidate an earlier fourth result. Neither a property change nor a snapshot read silently performs this getter.
6. Read back with `cp_start_state_data_snapshot` using the latest consumed source sequence. `known_mask` bits 0..3 describe the four data bytes. `predicate_known_mask` bits 0..4 describe profile, M, C, kind and Q. `snapshot_copied` reports the copy, while `data_ready` requires all four result bits. Business/configuration readiness, publication, AP application and publication generation remain zero.
7. `cp_start_state_data_build_reply` accepts only command `3003` or `3000`, only after all four result bytes are known from this owner. It builds exactly 16 bytes: type 1, explicit virtual reserved byte +1=0, LE16 command, LE32 echo at +4, LE32 `f000` at +8, four data bytes at +12. It performs no I/O and grants no send, ACK, lease or publication authorization. The parent runtime must supply those independently.

All operations preserve state/output on failure. Missing source data returns `-ENODATA` (`CP_START_STATE_SOURCE_BLOCKED`); malformed masks, pointer arithmetic wrap, typed-object misalignment and forbidden overlap return `-EINVAL`; wrong process/origin returns `-EXDEV`; torn/unquiescent transactions return `-EAGAIN`; stale source sequences return `-ESTALE`; size errors return `-EMSGSIZE`; unsupported commands, events and ADJ forms return `-ENOTSUP`. The caller must provide accessible immutable memory for every declared span and external serialization; the API cannot discover mapped memory or validate a dishonest quiescence declaration.

Input bytes/masks may share read-only storage. They may not overlap the mutable owner, including any mask-capacity tail. No input pointer is retained. Output cannot overlap the owner or guard. Logical mask bytes must be exactly 0/1; unused capacity tails are not scanned.

## Evidence, findings and source path

The public image identity is SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`, length 18,090,880 bytes. The only mapping used is `CP_VA = raw_offset + 0x108000`, valid in `[0x108000,0x1248b80)`. All pin ranges are checked against that interval before slicing. BSS addresses are names for runtime source dependencies and are never read as file offsets.

| Evidence | Source reference and finding | Content check / reproduction |
|---|---|---|
| E-imports | Raw ARM/Thumb image, not an ELF import table. Relevant source calls are the ARM memcpy at `61e60c`, allocator `565204`, sender `564b38` and release `565300`; these are internal transport dependencies. No general import survey is claimed. | Full-image identity and bounded call windows in the pin test; ELF import metadata is n/a for this raw image. |
| E-copy | `3ab4c0(T,P)`: `3ab4d0` saves P in r4; `3ab58a` stores it at `[sp,c]`; `3acb86` restores it into r5. `3ab4cc/d2` sets fp=`10e3180`. `3acc38/3a/3c/44` passes r0=P, r1=fp, r2=`348` to memcpy. | Pins `collector-*`, `ARM-memcpy-direction`; reproduced by the Python source-pin test. |
| E-root | `4daa6c` passes root+`3e80` to `992710`; the whole writer forwards P to the collector. `b2ec2e/32` puts root+`3e80` at table+`34`; `b2ddb4` returns table `173efe8`. Reply getters load table+`34`, offsets `46/47/48`. | Pins `root-*`, `whole-writer-*`, `reply3003-and3000`. |
| E-initial | File-backed cache `10e31c6/c7/c8` is exactly `00 00 00`. This seeds only the local cache before the first source sample, not native history or result readiness. | `cache-image-initial-three`, exact hex plus SHA-256. |
| E-status | Collector `3abb86..3abd68`, tuple helper `99fdbe`, action helper `99fe78`, raw LIF getters `a4c27c..a4c30a` and override getter `99e250`. | Matching named pins; host tuple/flags/action/override matrix. |
| E-notify | `9aa484`, `9aa4f6` and flags notification `50fdf4` construct independent 20-byte messages. They contain no direct status-cache stores. With SID `811006e9`, `564b38` selects the registered remote hook; table `11d7914` gives `bee174` (mode 0), which reaches `56a994`. Its mode-0 success path queues through `beedca`, skips the mode-1 wait, and records statistics. | `*-notification`, hook/queue/statistics pins. This establishes separation of immediate owned data updates from asynchronous notification delivery; it does not establish a receiver's later business effects. |
| E-fourth | `a9885e` computes from profile/kind/Q; `a499f4` selects M/C. `a48ba2..a48c10` registers the actual property contexts and copies delivered payload into context. `a9170c/1a/30` clear/copy/return Q; `a94b86` reads current predicate kind. | Fourth/property/Q/kind pins and exhaustive host byte tests. |
| E-adj | `a48f6c..7a` registers pointer table `19ee17c` as group 9 through `b22f1e`. Key `0a` selects `b24cc4`; selector 0 and op `ff` copy payload bytes through the selected group pointer. Index `80` targets M=`1b18337`; index `b2` targets C=`1b18359`. | ADJ pins; bounded packet and invalid/partial/multibyte host tests. Pointer-table targets are runtime dependencies, not BSS file reads. |
| E-bootstrap | `a4bd3e` copies 600 bytes from mutable `169d958` to `169dbb0`. `99affc` copies a supplied 200-byte pointer bank to `165cfb0`. Neither establishes the requested live fields or override pointee defaults. Profile's file byte is 0, but property prefetch/delivery can overwrite it. | LIF-copy, pointer-bank-copy and property pins. The model does not promote these facts to known native startup input. |

Each pin has its source VA, raw offset, length and SHA-256 in [source-pins.json](source-pins.json). Exact short instruction/data windows also contain expected hex. One command above reproduces all content checks.

| Finding | Severity | Evidence | Confidence / location / status |
|---|---|---|---|
| F1: The first three reply bytes have a positive writer and copy-out path. | n/a_re | E-copy, E-root, E-initial, E-status | High; collector/root/reply chain; implemented and host tested. |
| F2: Unknown old flags can make a first complete zero-flags sample ambiguous. | n/a_re | E-status, E-initial | High; flags-clear after tuple update; preserved as `-ENODATA`, with explicit history consumer. |
| F3: Fourth-byte C is full u8 in mode 1, and M=2 updates C only when its getter runs. | n/a_re | E-fourth, E-adj | High; `a499f4`; implemented with explicit getter event and invalidation. |
| F4: Notifications are separate immediate transport work; delivery is not owned-data readiness. | n/a_re | E-notify | High for the pinned mode-0 path; delivery/business effects remain outside this owner. |
| F5: Native startup inputs remain unclosed. | n/a_re | E-bootstrap | High for the absence of a proven bootstrap in this investigation; no claim of a whole-image negative proof. Explicit producer callbacks/events are required. |

P1 (`path_type=callflow`): root `172fe50` → P=root+`3e80`=`1733cd0` → whole writer `992710` → collector `3ab4c0(T,P)` → cache `10e3180` status update → memcpy(P,cache,`348`) → table `173efe8`+`34` → reply bytes P+`46/47/48`=`1733d16/17/18`. Fourth-byte flow is actual property/kind/Q plus ADJ M/C → `a9885e` → `a499f4` → reply+`f`. This chain replaces the earlier negative conclusion that the cache was a different object with no copy-out.

The bounded implementation timeline is: verify the public image identity and copy-out windows; inspect the notification wrappers and registered async path; publish the owner API; implement data and getter consumers; compile/run the host sanitizer matrix; pin/recheck source windows; add boundary regressions and retest. No native history was generated during these steps. Report flavor is ordinary firmware reverse analysis (`null`).

## Exact status semantics

The LIF input is exactly `0x129` bytes relative to `169dbb0`. Known source fields are kind `+81`, state `+82`, subcode `+83`, LE32 flags `+84..87`, action `+128`. Override mode is byte `+1c8` of the pointee of `165cfb0`, supplied as an exact `0x1c9`-byte span. Mode-1 alternate kind/subcode are bytes `+0/+2` of `1b160ef`, supplied as a three-byte span.

1. Write the live tuple and apply `99fdbe`: on a changed tuple, leaving states 1/3 clears the first pair; state 1 with kind `60/61/62` sets the first/second/both bytes, even when the tuple is unchanged. Unknown prior tuple history cannot arbitrarily choose a clear branch.
2. Flags changing from nonzero to zero clear the pair; bit 1 sets the second byte and bit 5 sets the first. Other set bits and high u32 bits are preserved as input domain. If unknown previous flags make clear-versus-retain observable, the transaction fails atomically. Later action/override writes may resolve that uncertainty.
3. Let `x=(action-1)&ff`. For x=0/1/2, set effective action and byte 3 to low8(`10000 >> (8*x)`), hence 0/0/1; action 1 sets byte 1 and action 2 sets byte 2. Other actions clear effective action and byte 3 without clearing the pair. Raw input action remains full u8.
4. Override mode 2 captures the live kind/state/subcode/action and runs the tuple helper again. Mode 1 merges in this precedence: kind `11`, kind `10`, subcode `61`, kind `62`, kind `61`, kind `60`, otherwise zero. The first two yield `(kind,3,61,2)`, the subcode case `(0,3,61,2)`, kinds `62/61/60` yield `(kind,1,32,1)`, and fallback is `(0,0,0,0)`. Apply tuple and action helpers again. Other override-mode u8 values use normal live processing.

The fourth getter computes 1 for profile 2; for profile 1, it tests whether current predicate kind is 1/2/3; otherwise Q must satisfy Q0 in 1/2/3, Q1=9, Q2 high nibble=`20`, Q3=`13`. M=1 returns the full u8 C; M=2 stores computed into C then returns it; all other M values return computed. An explicitly known M=1/C result is independent of unknown computed inputs: the preceding source computation has no result-side mutation in that branch. No Boolean clamp is applied to C.

The supported ADJ packet is exactly `0x31` bytes with known op `+26=ff`, LE16 index `+28=0080/00b2`, key `+2a=0a`, selector `+2b=0`, LE32 length `+2c=1`, and one full-u8 payload at `+30`. Other packet forms, including multibyte aliases, are rejected rather than partially interpreted.

## Validation and remaining dependencies

The C matrix covers rising/falling flags, state transitions and unchanged tuples, all 256 actions, mode-2 capture, merge precedence and unknown merge bytes, profile/property delivery, Q clear/copy and 1,024 Q-byte variations, all 256 predicate-kind values and all 256 M=1 cache values, getter-time M=2 writeback, partial/invalid/multibyte ADJ packets, unknown-zero refusal, reply echo/command/reserved-byte layout, source immutability, read-only aliasing, mutable overlap including mask tails, range/alignment/size/mask errors, PID/fork/origin guards, torn/stale source transactions, revision overflow and unchanged state/output on errors. Snapshot/publication/business distinctions are asserted explicitly.

A production binding still needs actual virtual LIF/status producers, previous-state history where observable, property repository/delivery history, ADJ M/C source writes, and the current predicate-kind/Q producer events. Native LIF initialization, override pointee defaults and native M/C initialization are not guessed. Async notification reception and its later effects need separate actors. This owner performs no 76-getter publication, CP-current application, AP application, lease integration or end-to-end VM check; those remain with the parent unified batch.
