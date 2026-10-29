# Integration contract

Include `runtime/analysis/device-models/cp-parameter-state.h` and link its C file together with `cp-parameter-batch.c`. Initialize an explicit caller-owned `struct cp_parameter_state` using `cp_parameter_state_init(owner, true)`. Feed the actual same-run AP message to `cp_parameter_state_consume(owner, source, target, data, length)` under the existing source lock. Input must remain immutable until return. The fixed stager validates the full type5/4063/a04 envelope and all 190 headers before any field writes.

A successful partial transaction returns `CP_PARAMETER_STATE_PARTIAL`. `config_consumed` records complete source-local writes per slot; `semantic_complete` additionally requires source business semantics to be closed. A partial result must not advance the CP publication generation, send ACK, publish state, or assert readiness. The model has no generation/ACK APIs. A second transaction requires explicit reinitialization and otherwise returns `-EBUSY`.

`bytes` is the explicit virtual image for the source object at `0x165a720`, size `0xd64`. `known_mask` has one bit per byte (bit `offset % 8` in byte `offset / 8`). Use `cp_parameter_state_read` for strict readback; unknown bytes return `-ENODATA` with output unchanged.

For the cp-start-state-provider worker: **P+0x1c8 is not established by the currently closed 4063 setters**. Plain `cp_parameter_state_init` still leaves it unknown. A separate source-positive `cp_parameter_state_consume_reset_store` executes only CP8db6d6's explicit STRD zero write over `[1c8,1d0)`, once before staging, and marks those8 local bytes known. This is an explicit source write event, not a BSS/default-property guess or full-constructor completion. The reset-only API remains available. The default-off owned-state constructor now consumes the complete source-local common phase (694 bytes), then only after the authenticated CP initial-stage property decision selects flag0, consumes default local stores (2223 writes;2913 known combined). Both phases keep initialization_complete=0. See [the reset source contract](../cp-override-input-contract/README.md), [common writes](../cp-parameter-initializer/README.md), and [default writes](../cp-parameter-defaults/README.md).

Do not bind this local image as the `165cfb0` pointee T0 without independently proving publication and bank history. The provider expects one0/1 known byte per data byte; expanding the local bit mask does not prove that publication. The owned profile explicitly copies the current d64 image into a separate [parameter view](../cp-parameter-publication-contract/README.md), then binds its bank0. This establishes an owned immutable data copy, not original publication/generation. No local reset/default byte is automatically fed to the3003 data owner. Actual packet staging alone still proves neither the pointee nor its mode.

No integration/profile/menu/build files are changed by this worker. No VM was launched; the parent owns joint self-test and the single end-to-end VM.

## Separate config word, bank3 and FLAGB

**Rebuild every `cp_parameter_view` consumer:** its caller-owned struct has grown;
existing function signatures and the d64 bytes/mask/bank0 history are preserved.
Known consumers are `menu-observe.c`/`build-observers.sh`, the existing C harness,
and the extracted helper in `test_cp_owned_inputs.py`. This worker changes only
the view module, its tests and these notes; the parent owns observer integration.

The [closed source contract](../lif-enable-input-contract/README.md) and its
[source pins](../lif-enable-input-contract/source-pins.json) bind a separate
304-byte config copy: `S+1144=1730f94` -> `1731298`, with
`bank3=1730c68`, `bank3+64c=copy+1c=17312b4`. This lies outside the d64 P copy.
The model retains only the consumed LE32 word and its knownness, never the other
300 bytes or whole-bank knownness. Plain init leaves the source word, copied
word, binding and FLAGB unknown/unbound, even though storage is zeroed.

Under the same process/origin lock and quiescent even guard, consume these
explicit local events (the parent's example sequence follows bank0 binding6):

1. At8, `cp_parameter_view_consume_config_constructor_store(view, guard)` models
   only `b2a82a -> b2a540`, source `+1c=2`, once before the first config copy.
2. At10, `cp_parameter_view_consume_config_copy(view, guard,
   CP_PARAMETER_VIEW_CONFIG_COPY_INITIAL, NULL)` copies that owned constructor
   word. Alternatively pass an actual `cp_start_state_span` with `size=304`,
   `known_size>=304` and strict0/1 logical mask bytes. It does not bind bank3.
3. At12, `cp_parameter_view_consume_bank3_binding(view, guard,
   CP_PARAMETER_VIEW_BANK3_VA)` binds only this logical identity.
4. At14, `cp_parameter_view_consume_flagb_store(view, guard)` executes the
   `3a9d48 -> 99b86e -> a4dfc6` getter/store, FLAGB=`word==0` at169e018.
5. Still at14, `cp_parameter_view_copy_flagb(view, guard, readback)` returns a
   caller-owned `cp_parameter_view_flagb_readback`. Constructor, copy, binding
   and derived store sequences and copy-input provenance are separate fields.

For every actual later `b2ee12` event, use `CONFIG_COPY_RECOPY` (full enum name
`CP_PARAMETER_VIEW_CONFIG_COPY_RECOPY`) with the current304-byte caller span;
NULL cannot replay the historical constructor. All four word bytes must be known
for the source observation and copied word to be known; caller spans refresh
both, without changing the historical constructor-store sequence. Unknown input
is a successful copy event that revokes FLAGB, as does every known/equal-word
recopy. Until a new actual getter/
store, FLAGB readback returns `-ENODATA`, leaving older caller output untouched.
A newer guard without a consumed event returns `-ESTALE` for known FLAGB
readback; the immutable bank0 read keeps its existing later-sequence behavior.
Callers must honor errors and feed each actual copy; unobserved native history
cannot be reconstructed from this local model.

A valid guarded wrong bank3 root returns `-ENOTSUP` and revokes only bank3/FLAGB
until reinit. It leaves the d64 copy, mask and bank0 binding untouched. All other
errors are atomic, with existing PID/origin/fork/sequence/torn guards and full
input/output span overlap validation. No pointers are retained and no heap is
used. Tests directly exercise these APIs in `test-cp-parameter-view.c`, including
unknown and stale-zero refusal, recopy0 -> FLAGB1 only after store, endian/full
word values, bank0 independence and validation failures. Only syntax compilation
was run in this worker; pytest and the sanitizer C scenario await the parent's
single frozen batch. This feature establishes no FLAGA/property value, native
collector timing,3003 promotion, ready/ACK/publication/generation or capture.
