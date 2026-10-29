# Initial parameter copy and bank0 override view

The new [parameter view owner](../../runtime/analysis/device-models/cp-parameter-view.h) owns the complete `0xd64` bytes copied from the actual `cp_parameter_state` image, plus its packed known mask. A second explicit event binds bank0 to that copy. Only then can a caller export `[0,0x1c9)` as separate bytes and strict `0/1` known arrays for `cp_start_state_data_consume_lif`. No pointer into the mutable source or the view is returned or retained. Ordinary unknown source bytes stay unknown, including a missing override mode.

This is a local virtual data-flow implementation. It does not prove native boot, complete parameter initialization, periodic publication, business readiness, generation advancement, ACK, AP application or capture. All such claims remain false. The source common initializer models 195 local-store instructions and 694 known bytes, including the eight-byte reset at `P+0x1c8`; its AE tail, old-state paths and default initialization remain outside this subset. The native producer remains unverified.

Scope is the authorized public ALLLANG source and local host owner tests. This work does not start a VM, use a network, access private/full assets, touch a camera or pass through a physical SD. The source binary stays read-only and is not redistributed. The report flavor is `null`; no malware or exploit behavior is claimed.

From the native-camera result root, reproduce the dedicated tests with:

```sh
cd runtime/analysis
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib -q \
  test_cp_parameter_view.py
```

The test compiles the actual parameter state, batch and LIF owner together with the new view under `-std=c11 -Wall -Wextra -Werror -pedantic -fsanitize=address,undefined`. The raw-source test requires the separately prepared public `menu-root/cp/cpapp-b.bin`; it explicitly skips if that asset is absent. The model and metadata tests still run. In this workspace all three tests pass, including the raw-source test.

| Evidence | Finding | Path |
|---|---|---|
| `4b7028` window, branch calls at `4b704a` / `4b7070` | Both boot branches call `353d48`, then converge through `c1aa3e` before the `4b708a -> b2e140` call. Completion of `c1aa3e` is unproved. | Boot parameter loading → later copy constructor; no complete boot claim |
| `b2e140`, especially `b2e150` and `b2e164` | `8dad4a` supplies `P=165a720`; the caller argument is not P. `memcpy(S=172fe50,P,0xd64)` has no earlier ready/generation gate. | Actual source image → immutable owned copy, including unknown bytes |
| `b2e656..668`, `b2e8e0`, `b2e8e8 -> b2ebce` | Construct `T=173efe8`; `b2ebd2:0860` stores `T[0]=S`; `b2ec2e/32` store `T+34=S+3e80`. | Image copy → separate logical bank0 binding event |
| `99affc/99b00c`, `99e250` | Copy `200` bytes, meaning `50` u32 pointers, into `165cfb0`; the getter dereferences bank0 then byte `+1c8`. | Bound bank0 → caller-owned override projection |
| `3abc42` window, collector `3abc46` | The collector calls the getter: mode0 uses normal LIF, modes1/2 alter processing. | Actual mode byte and known bit → existing LIF consumer |
| `b224a8` / `b224ae` | The 3003 tail reads `T+34` cache bytes `46/47/48` and the fourth getter. It does not recollect, copy parameters or bind bank0. | Replies consume previously owned state; no implicit refresh |
| `8dad4a` window including `8dad54` | The periodic `0xd64` copy requires lock `26` to return zero; pending callbacks/queue matter. | Periodic publication is excluded from this initial-copy model |
| Source parameter handlers, as recorded in the delegated source contract | 4072 sets only `P+348/349`; 4063 increments `P+d5c` after its handlers. Neither operation automatically copies S. | Later mutable writes leave this owned image unchanged |

[Source pins](source-pins.json) record ten windows totalling 5,480 bytes. The original public CP image is 18,090,880 bytes, SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`. Each window is checked independently against the actual image. CP virtual addresses map to raw offsets by subtracting `0x108000`, strictly inside the file-backed interval `[0x108000,0x1248b80)`. No BSS byte is read as file content.

The API is deliberately limited to the initial-copy subset:

| Call | Required state and result |
|---|---|
| `cp_parameter_view_init` | Binds the current PID, origin `NONE`, empty mask, no copy and no bank binding. Reinit explicitly discards the prior copy. |
| `cp_parameter_view_consume_initial_copy` | Valid matching quiescent guard and accessible source; validates the actual source through `cp_parameter_state_read(source,0x1c8,&local,1)`. Success and `-ENODATA` both permit the opaque full copy; invalid magic, wrong source PID or disabled source reject it. Exactly one copy per init; repeat is `-EBUSY`. |
| `cp_parameter_view_consume_bank0_binding` | Requires a copy and logical root `CP_PARAMETER_VIEW_PUBLISHED_VA` (`172fe50`). This is a symbolic operation; the numeric address is never dereferenced. Records a distinct bank sequence. Repeated matching binding is `-EBUSY`. |
| `cp_parameter_view_copy_override_span` | Requires copy and valid bank0. Copies actual stored bytes and expands each of 457 packed known bits into a byte `0` or `1`. Returns success even when the copied override is unknown; downstream dependency checks decide whether it can be consumed. |
| `cp_parameter_view_invalidate` | Explicitly revokes bank0 and records the event, retaining the immutable copy, mask, copy sequence and prior bank sequence for diagnosis. Reinit is required before a new copy/binding. |

A valid guarded binding event with the wrong logical root returns `-ENOTSUP`, revokes bank0 and permanently invalidates that copy. This is the sole error that intentionally changes the owner, so a subsequent export cannot reveal an old bank after a rejected rebind. Export or matching rebind after invalidation is `-ESTALE`. Malformed guards and invalid source/capacity/alias errors leave owner and outputs unchanged.

Guards use the existing `cp_start_state_guard`. Their PID must match both this owner and the current process; source validation also checks the parameter state's batch owner. Origin must be `VIRTUAL_SOURCE` or `HOST_TEST`, and cannot change after the first event. Host origin stays host origin. `quiescent` must equal one, both sequence values must match and be even, and sequence must not go backwards. `copy_sequence` and `bank_sequence` record their actual events; `source_sequence` records the last consumed event. A later guarded read is allowed without refreshing the immutable copy or advancing its event diagnostics. These are local transaction sequences, with no native generation meaning.

Callers serialize all source/view access externally, including source init and mutation, and guarantee declared spans are accessible. Typed owner and guard alignment, pointer-range wrap, source/owner/guard overlap, and complete output capacity ranges are checked. Byte outputs require no additional alignment. Source packed mask bits accept all byte patterns; unused padding bits are preserved but never expanded as image bytes. Output mask bytes initially containing nonbinary values are overwritten with strict `0/1` inside the logical span, while capacity tails remain untouched. Both output capacity ranges must be disjoint from each other, the view and guard. The exporter has no source pointer and therefore no dependency on source lifetime. No internal lock or memory-mapping probe exists.

For integration, use this order under one externally serialized virtual owner:

```c
struct cp_parameter_view view;
unsigned char bank_bytes[CP_PARAMETER_VIEW_OVERRIDE_BYTES];
unsigned char bank_known[CP_PARAMETER_VIEW_OVERRIDE_BYTES];
/* source: initialized cp_parameter_state with real consumed local stores.
 * g4/g6: same PID/origin, matching even sequences 4 and 6, quiescent=1. */
int rc = cp_parameter_view_init(&view);
if (rc == 0)
    rc = cp_parameter_view_consume_initial_copy(&view, &g4, &source);
if (rc == 0)
    rc = cp_parameter_view_consume_bank0_binding(
        &view, &g6, CP_PARAMETER_VIEW_PUBLISHED_VA);
if (rc == 0)
    rc = cp_parameter_view_copy_override_span(
        &view, &g6, bank_bytes, sizeof(bank_bytes),
        bank_known, sizeof(bank_known));
/* On success the caller may build a cp_start_state_span over these arrays.
 * Consume it only with the actual known LIF dependencies and matching guard.
 * Do not call the copy or binding operation from a 3003 reply handler. */
```

The [C tests](../../runtime/analysis/device-models/test-cp-parameter-view.c) verify the complete `0xd64` image and packed mask against the actual owner, then every byte and expanded known bit of the exported span. They cover both real common/reset stores and ordinary full-unknown init, poisoned unknown storage, unused mask padding, independent copy/bank sequences, source reinitialization, source destruction with ASAN, all 256 mode values under explicit host fixture injection, repeat copies, bind before copy, wrong-root invalidation and explicit revocation. Host fixture edits are explicitly marked and provide no claim about an unmodeled native setter.

Negative tests exercise malformed/stale/torn guards, origin/PID mismatch, disabled or invalid source, forked owners, null/misaligned typed pointers, source/guard/owner alias, output/owner/guard alias, both capacity tails, capacity wrap and short output buffers, with unchanged-output assertions. The actual LIF owner rejects a fully known override when its real LIF fields are missing, accepts the common-store mode0 when those fields are supplied, rejects an unknown copied override, and rejects a nonbinary caller-corrupted output mask. A successful local LIF reduction still has only its own data knowledge and leaves business/configuration/publication/AP flags false.

Existing parameter initialization, runtime profiles, reply dispatch, full snapshot, property and LIF source production are outside these added files. The main session owns runtime integration and broader regressions. Periodic refresh, callback/pending semantics, full native startup, capture and hardware behavior remain unverified; adding them requires their own consumed source events and evidence.
