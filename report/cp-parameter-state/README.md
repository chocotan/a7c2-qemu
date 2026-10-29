# CP4063 parameter-field consumers

The new caller-owned model consumes 170 of the 190 slots' complete local parameter-write algorithms through 303 immutable field descriptors. It marks 168 source business handlers semantically complete: 164 field-writing handlers plus three exact no-op handlers and one debug-only handler. Six additional handlers consume their local configuration fields while retaining incomplete business semantics. Sixteen handlers remain unsupported and their parameter fields remain unknown. Actual same-run packet consumption establishes 891 bytes of the 3428-byte image; 2537 bytes remain unknown.

`P+0x1c8` remains unknown after plain init plus4063: no modeled4063 setter establishes it. A later source investigation found the explicit STRD at CP8db6d6; `cp_parameter_state_consume_reset_store` can now execute that single8-byte local initialization write before staging. The default-off owned-state constructor now uses all source-local common stores (694 known bytes), followed by the original flag0 default local writes only after the explicit CP initial-stage decision (2913 known combined). The actual4063 byte replay reaches2973/3428 known bytes while preserving PARTIAL and the original semantic masks. Full constructor/business completion remains false. The [source contract](../cp-override-input-contract/README.md) and [integration note](INTEGRATION.md) distinguish its local known value from an actual published override. Receiving4063 or applying local writes alone does not prove the `165cfb0` pointee. The profile now executes separate owned d64 copy and bank0-binding operations through [cp-parameter-view](../cp-parameter-publication-contract/README.md); native CP startup/publication history is still unverified. The model returns `CP_PARAMETER_STATE_PARTIAL`, leaves `batch.semantic_applied=false`, and provides no ACK, generation, snapshot, readiness or capture operation. See [INTEGRATION.md](INTEGRATION.md) and [scope.md](scope.md).

| Classification | Slots | Meaning |
|---|---:|---|
| Configuration consumed and business complete | 164 | Source-local writes and entire business algorithm modeled |
| Configuration consumed, business incomplete | 6 | Local writes modeled; callee/business effects remain unknown |
| Exact no-op or debug-only business handler | 4 | No parameter writes; semantic bit set, config bit clear |
| Unsupported | 16 | No stores applied and no completion bits set |
| Total | 190 | Every slot classified offline in one batch |

The six configuration-only opcodes are `4008`, `407e`, `407f`, `4080`, `4097`, `40ac`. The unsupported opcodes are `4016`, `401a`, `4022`, `4023`, `4059`, `407a`, `4083`, `40a2`, `40d9`, `40e8`, `40f8`, `4103`, `4143`, `4155`, `4157`, `415f`. Exact no-ops are `4164`, `4172`, `4173`; `4104` only logs. [source-map.json](source-map.json) records all 190 handler VAs, raw SHA256 pins, reasons and field mappings. Proven diagnostic log calls are observational and omitted from business completion.

| Unsupported opcode | Blocking source behavior |
|---|---|
| 4016 | Saturating increment of unknown old P+1f4 |
| 401a | Increment of unknown old P+564 |
| 4022 | Context callee and conditional comparison/retain algorithm |
| 4023 | Context and business callees control conditional writes |
| 4059 | Increment of unknown old P+322 |
| 407a | Selector-dependent branches and helper |
| 4083 | Conditional business call for value 2 |
| 40a2 | Context-dependent normalization and business effects |
| 40d9 | Increment of unknown old P+d50 |
| 40e8 | Multi-branch configuration algorithm |
| 40f8 | Conditional reset depends on unknown old P+bd3 |
| 4103 | Callee result controls input remapping |
| 4143 | P+afc controls retaining P+b04 |
| 4155 | External state, arithmetic, counters and callees |
| 4157 | Conditional retain plus unknown old P+684 counter |
| 415f | Selector-dependent variable destinations |

Implementation files are [cp-parameter-state.h](../../runtime/analysis/device-models/cp-parameter-state.h), [cp-parameter-state.c](../../runtime/analysis/device-models/cp-parameter-state.c), [test-cp-parameter-state.c](../../runtime/analysis/device-models/test-cp-parameter-state.c) and [test_cp_parameter_state.py](../../runtime/analysis/test_cp_parameter_state.py). Initialization binds the current PID and leaves all bytes unknown. Consumption calls the existing complete 2564-byte stager on a temporary state before applying any descriptors. Source, destination, size, outer header and all 190 fixed slot headers must validate. Any malformed/provenance/range/alias/stale-owner error preserves the owner. An accepted packet is one-shot and retains its complete wire copy. Readback checks all requested known bits before touching output.

The admitted field operations are exact little-endian 8/16/32-bit loads and 8/16/32-bit stores, source sign/zero extension, bool normalization, equality-to-one normalization, boolean OR, fixed bulk copies, and the pinned `413f` conditional clear. For nonzero `413f` input the old P+2f4 value is retained with its existing knownness; no default is synthesized. Unknown-state increment/clamp cases are explicitly unsupported. Existing getters and layout JSON were references only; no getter-derived values were substituted for actual parameter consumption.

Evidence and findings (ordinary reverse engineering, flavor=null):

| Evidence | source_ref / content hash | Reproduction |
|---|---|---|
| E-imports | Public CP raw image: 18090880 bytes, full SHA256 above; headerless Thumb image has no object import/export metadata. Calls are direct source VAs, not inferred imported APIs. | Source proof test authenticates complete CP, then verifies bounded handler ranges. |
| E-dispatch | Existing fixed `cp_parameter_batch_slots`; source table VA `10fab8c`, stride 20; dispatcher `35ced4`; whole-batch caller `8da08c`; generation body `35ce2c`. Table/caller/generation hashes checked in the new Python test. | Run source-proof test below. |
| E-handlers | [handlers.asm](handlers.asm), [handlers.c](handlers.c), [source-map.json](source-map.json); 190 exact function entries in one Kuna invocation, eight-second per-function cap, discovery disabled; full raw pins per handler. | `python3 report/cp-parameter-state/generate.py` from the native-camera directory. |
| E-actual | Existing console sequence 49, pid 258/tid 381, 21 contiguous chunks, 2564 bytes. Packet SHA256 `ff6d35854ffeed873650d77ac8b7646b555883b338762306eb6d1120aacf7b74`; console SHA256 in [actual-batch-evidence.json](actual-batch-evidence.json). No actual payload or firmware image is redistributed here. | Actual same-run test reconstructs contiguous chunks and compares the entire image, known mask and 190 pairs of completion bits. |
| E-tests | [selftests.json](selftests.json); strict C11, Wall/Wextra/Werror/pedantic, ASan and UBSan. | Scoped pytest command below. |

| Finding | severity / status / confidence | Evidence / location / implication |
|---|---|---|
| F-fields | n/a_re / validated / high | E-handlers, E-actual, E-tests; generated field table. 170 config slots, 303 field stores, 891 known bytes after the actual message. |
| F-partial | n/a_re / validated / high | E-handlers, E-tests; separate 190-bit masks. Six local consumers have unmodeled business callees; 16 entire slots remain unsupported; complete result cannot be reported. |
| F-override | n/a_re / validated / high within implemented mapping | E-handlers, E-actual, E-tests; P+1c8 has zero known bits. Receiving this packet does not prove an override mode or the T0 pointee identity. The actual producer remains unclosed. |
| F-atomic | n/a_re / validated / high | E-dispatch, E-tests; all input validation precedes committed owner writes. Malformed slots including the final slot leave owner unchanged. |

P-001 (`path_type=callflow`): actual AP envelope `80020002 -> 90030001`, type5/4063/a04 (E-actual) → fixed source dispatcher slot selection (E-dispatch) → temporary existing stager → immutable field descriptors (E-handlers/F-fields) → bytes/known-mask and distinct consumption masks → PARTIAL (F-partial), strict override read blocked (F-override). Source generation increment at `35ce2c` follows complete source business processing; this partial model never executes or emulates that increment.

Verification from the native-camera directory:

```bash
python3 -m pytest runtime/analysis/test_cp_parameter_state.py -q
```

Result: **10 passed**. Tests cover full-byte normalization domains, conditional retained unknown state, full image/mask/flags comparison for actual and six host-pattern packets, complete CP identity and 190 raw-handler pins, reproducible offline table generation, all 190 corrupt opcode/type headers, outer corruption, every short size, wrong endpoints, owner aliases, pointer wrap, stale/forked owners, one-shot rejection, disabled owners and unchanged read outputs on failure. Image/actual-console tests explicitly skip only when those separately prepared assets are absent.

Timeline: fixed batch/API and existing getter references read → minimal stable header delivered to parent → all 190 exact handlers decompiled/classified in one offline batch → generated local consumers and transaction/readback checks → actual sequence49 decode → initial tests exposed JSON tuple/list comparison and one independently asserted field offset error; both corrected → scoped sanitizer/source/actual tests passed. No individual VM, root regression, network, real hardware or physical SD was used. Joint runtime integration and the single end-to-end VM remain the parent's responsibility.
