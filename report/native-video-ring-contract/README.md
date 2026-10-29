# Original MPR VideoInfo consumer ring helpers

This directory implements two bounded, caller-owned C helpers for the source-closed original MPR **consumer** contract. One copies opaque 96-byte VideoInfo records in ring order; the other plans a software read-index update after the caller actually processes slots. Neither helper publishes a slot, reads ES payload, retires an ES lease, accesses native globals, or completes a capture command. **Native recording stays unsupported: `NVIDEO_NATIVE_GAPS` remains 63, including `COMPLETION_LEASE` (16) and `MPR_PUBLICATION` (32).** No existing binding or runtime file is changed.

The public interface is [native-ring.h](native-ring.h), with implementation in [native-ring.c](native-ring.c). This is a standalone host module with no dependency on the component encoder or other new modules. Normal-type filtering, type-4 parsing, access-unit resolution and one/two-span ES handling belong to their separate consumers. All 96 bytes, including unknown metadata and control entries, survive copying unchanged. Timestamp units, source identity and SDS meaning are not inferred.

## Run the checks

From the native-camera result root:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider \
  report/native-video-ring-contract/test_ring.py -q
```

Result: **21 passing pytest cases**: ten C self-check modes in each of strict C11 and ASAN/UBSAN builds, plus complete artifact/window pin verification. The compiler flags include `-std=c11 -Wall -Wextra -Werror -pedantic`; the tests require only installed `cc`, Python and pytest. Executables are confined to pytest temporary directories. Source checks read the existing public ALLLANG assets under `runtime/analysis/menu-root` without writing them.

Checks compare all bytes of nonzero synthetic HOST records, including one/two-slot lists, wrap, exactly `N-1` available, empty `N=1` and `N=2`, and the last-processed `R+1` convention. They cover every active status (1/2/3), slowest-user retirement, inactive/unknown-status skips, duplicate IDs, missing users, zero-count shared movement, bounded counts, 64-bit intermediate index arithmetic, truncated storage, null/misaligned/wrapping spans, whole-capacity aliases and untouched outputs/inputs/errno on errors. Small rings are compared against an independent modulo-based host model. The implementation itself uses subtract-once wrapping.

The complete HOST flow reads actual fixture bytes, compares every byte in a test consumer, plans retirement, then explicitly applies the returned software values for two users. That comparison is host slot processing only. No native ES decode, native capture, native completion, VM or file recording is claimed.

## Copy a coherent read list

`nring_copy_read_list(ringbytes, ring_capacity, N, W, Ruser, out_bytes, out_capacity, &out_count)` copies **every available record** or returns an error before changing any output. Capacities are bytes; the result count is slots.

The source cursor denotes the **last processed** slot:

```text
available = W >= Ruser ? W - Ruser : W - Ruser + N
next      = Ruser + 1 >= N ? Ruser + 1 - N : Ruser + 1
slot      = base + next * 96
```

Thus `N=5, Ruser=3, W=1` copies slots `4, 0, 1`. Equal cursors mean an empty list; the maximum representable availability is `N-1`. No producer/full-ring interpretation is added. The caller supplies a coherent immutable source snapshot under the actual external source lock. The helper changes no cursor and does not interpret the records.

`N` must be positive, all cursors must be below `N`, and ring storage must cover `N*96` bytes. The output capacity must hold the entire list. Both full declared buffer extents and the aligned `out_count` object must be mutually disjoint, including unused tails. `out_bytes=NULL` is permitted only with zero capacity and an empty list. Integer address-span checks cannot prove that memory is mapped: the caller must supply valid accessible objects for every declared extent. There is no heap allocation, partial copy, callback or retained state.

## Plan retirement after actual consumer work

`nring_advance_read(users, user_count, user_id, returned_count, borrowed_count, N, W, shared_read_index, &result)` reads a typed host projection and returns only:

```c
struct nring_advance {
    uint32_t user_read_index, shared_read_index, delta;
};
```

`struct nring_user` contains `{uint32_t id, read_index, status}`. This host struct is **not** the original serialized record: that has stride `0x24`, with ID at `+0`, read index at `+4`, and status at `+0x1c`. A future source adapter must explicitly extract only those proved fields. It must resolve library-relative addresses itself; this module does not map guest memory.

All IDs must be unique, including inactive records. Statuses 1, 2 and 3 are active; every other status is skipped when computing the shared minimum. Inactive cursors are not read for index arithmetic and need not be in range. The selected user must exist and be active; all active cursors, `W` and the shared cursor must be below `N`.

The caller supplies the actual `out_count` from the same immutable read-list snapshot as `borrowed_count`, and only actually processed slots as `returned_count`. The helper checks `returned_count <= borrowed_count <= N-1` and `borrowed_count <= distance(W, selected.Ruser)`. **These numerical checks cannot authenticate the caller's count or prove ES bytes were consumed.** No boolean completion gate, fake lease token or synthetic completion identity is introduced.

The planned values follow the original setter:

```text
newUserRead = wrap_once(selected.Ruser + returned_count, N)
delta       = MIN(distance(Ri, oldSharedRead)) over all active users
              using newUserRead for the selected user
newShared   = wrap_once(oldSharedRead + delta, N)
distance(a,b) = a >= b ? a-b : a-b+N
```

`CalcRingIndex` subtracts `N` once, rather than taking general modulo. Bounds above keep each sum below `2*N`; the implementation uses `uint64_t` intermediates and checks host `size_t` multiplication and spans. At least the selected user is active, so the minimum always has a candidate. `returned_count=0` succeeds and may advance the shared cursor if every active cursor is already ahead of it. The user table is never mutated by this helper.

After actual native consumer completion, the caller applies the plan under the actual external source lock: store the selected user read index, perform the source-appropriate release barrier, then store the shared read index. Original M`27f5a0` contains **`DSB SY` before the shared store**. This pure planner executes no barrier, C atomic, shared store, MMIO operation, lease free or completion callback. A future adapter must preserve the actual source synchronization and coherent-snapshot lifetime; a host-model assignment does not establish that binding.

Both functions return `0` or a positive errno code and preserve the caller's `errno`. Every error leaves all input and output bytes/counts unchanged:

| Code | Rejection |
|---|---|
| `EINVAL` | Zero `N`, required null pointer, misalignment, overlapping declared spans or duplicate IDs |
| `ERANGE` | Out-of-range cursor, too many returned/borrowed slots, or borrow beyond snapshot availability |
| `EOVERFLOW` | Host byte extent/product or integer address span wraps |
| `ENOSPC` | Truncated ring storage or insufficient complete-list output capacity |
| `ENODATA` | Selected ID absent, including an empty user table |
| `ENOTSUP` | Selected record exists but its status is inactive/unknown |

The original native setter returns 0 for the software index operation, including count zero, and 3 for an invalid stream/user. Host errno codes are defensive adapter errors; they are not original firmware return-code translations. The helper operates on one explicitly supplied channel, without inventing stream policy.

## Source evidence and integration boundary

[source-pins.json](source-pins.json) records ten supplied handoff windows, **4,760 bytes total**, with full-artifact sizes/hashes and window hashes. The tests check all bytes against public ALLLANG `usr/lib/libmpr.so` (3,528,576 bytes, SHA-256 `4fb6d886c1ac620399d09c9c2ffc074315968cf0ada764062913c4e0783fc7f9`) and `system/av-cam.bin` (13,797,088 bytes, SHA-256 `90343f5f2edc0393ad8809d907cfe648dfd3a82ce0ef39cf06167929d8955096`). M coordinates are ELF VAs equal to file offsets in the first load `[0, 0x2e4534)`; K coordinates are raw offsets. Global addresses below are library-relative, **not guest physical addresses**.

| Stream | Slot-base pointer | N (u32) | Shared-read pointer | Write pointer | User vector |
|---|---|---|---|---|---|
| 0 | `3b7f70` | `3b80b0` | `3b7e58` | `3b7e68` | `3b8148` |
| 1 | `3b7ef0` | `3b8080` | `3b7e08` | `3b7e18` | `3b8108` |

| Evidence | Finding | Path consequence |
|---|---|---|
| E1: M`2820fc` and M`27f4a8` including M`27f540` | F1: 96-byte full-record copies, last-processed convention and subtract-once index arithmetic | P1: bounded opaque read-list copy |
| E2: M`27f5a0` | F2: selected-user advance, minimum active distance, barrier and shared store; zero is software-operation success | P1: pure index plan; actual synchronization/store remains caller-owned |
| E3: M`11b54c`, M`120224`, M`282fb8`, M`11bed0` | F3: original consumer context, actual read call at M`11b57c` via PLT `7dae0`, setter at M`11b6e0` via PLT `7d680`; second caller stores/checks setter result at M`120230..244` | P1: copy and consumer work precede count return; slot copying alone proves no ES completion |
| E4: M`283e74`, M`27da20`, K`138720` | F4: actual `CallbackFromAvbbc`, actual `GetMessage`, and existing RMC boundary supply no closed producer/lease completion contract | P2: native capture/completion remains blocked |
| E5: strict C11 and ASAN/UBSAN host checks | F5: bounded copies and planned index values satisfy positive/error cases and full-byte comparisons | P1: host software helper verified; no native runtime claim |

P1 (`path_type=callflow`): coherent external snapshot → copy opaque slots → actual caller consumer work → bounded retirement plan → caller's actual user store/barrier/shared store. Only copying and planning are implemented here. P2 (`path_type=callflow`): native hardware/producer → original 96-byte ring publication → native consumer/completion/lease integration remains unbound. In particular, M`27fc9c` `PiWrite` and M`27fd6c` `InfoWrite` belong to the handoff's separate **40B/580-stride object** and are not reused as a VideoInfo producer. M`283e74` and M`27da20` are not index loops.

Scope: implementation from the supplied closed handoff, confined to these six new files. No new binary/call-chain research, existing file edits, full regression, independent review, VM, network, physical hardware/SD, private/full-system assets or native ACK path was used. Sequence: read project and existing binding contracts → publish header → implement helpers and host checks → verify both builds and all pins → document the contract. Formal report flavor is null; there is no vulnerability or IOC claim.
