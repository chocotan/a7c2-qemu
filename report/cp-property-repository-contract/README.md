# CP primary property repository: explicit public initial stage

The new `cp-property-stage` owner consumes the exact authenticated public `ALLLANG[0xed000:]` initial stage as an explicitly selected virtual **CP_PRIMARY** repository at supplied CP base `0x04000000`. It reads full properties `01250003`, `01250006` and `000d003a` from that same transaction, retains mode 1 and both complete 256-byte profile/ALH contexts, and can deliver the actual profile byte 0 through the existing start-state provider. Construction alone sets the source-file mode initializer 3 and leaves all three property-known flags false. This establishes a bounded virtual source binding; original CP startup, the PCI-to-CP alias and original execution/consumption history remain unverified.

The previous public provider's file-offset-zero PRIMARY policy remains unchanged: it lacks both properties, returns `-ENODATA` and performs no fallback. A file's second BK4 bank and the original CP secondary-repository pointer are different concepts. This adapter does not select `SECONDARY_VIRTUAL`, rewrite old repository enums or infer CP repository identity from ALLLANG file position. No default runtime operation, CP ready bit, full snapshot, send, publication, AP application or capture is added.

This is the scope record for an authorized, offline public-firmware implementation. The ALH extension changes only `runtime/analysis/device-models/cp-property-stage.{c,h}`, `test-cp-property-stage.c`, `runtime/analysis/test_cp_property_stage{,_file}.py` and this report's `check-original-abi.c` / `README.md`. Source pins and all eight original CP windows are unchanged. Existing provider, host profiles, menu and build files are preserved. No system VM, network, camera, physical SD, private configuration or full-system assets were used. Report flavor is `null`; no vulnerability is claimed.

## ALH initial payload integration

E-ALH is the already delivered [LIF enable-input evidence](../lif-enable-input-contract/README.md) and its unchanged [source pins](../lif-enable-input-contract/source-pins.json). The same full-ID BK4 lookup now requires attribute 8 and exactly 256 ALH bytes before the existing FNV check and atomic commit. Readback adds `alh_property_known` and `ALH_context[256]`; zeroed initial storage has known=0. Function names and existing field offsets are unchanged, but the containing structs grow, so all consumers must be rebuilt together.

| ALH evidence | Authenticated value |
|---|---|
| Full ID / section | `000d003a`; section entry `14e`, count 108, first 4238 |
| Property entry | Stage `78e2`: `08009ad503ff`; attribute 8 |
| Length / payload | LE16 256 at `3d59a`; payload at stage `3d59c` / ALLLANG `12a59c` |
| Complete payload SHA-256 | `b3dcc9455b88ff528026e892fab01a54c0c1ce80e4ccb9fd370b71d02a5c4c0c` |
| Paired CP tables | Index **`0x29` (decimal 41)** pairs context `1ac029c` and full ID `000d003a` |
| Retained byte `b8` | `ff`; no current gate value is inferred |

E-ALH → F-ALH: the owner retains the actual complete public initial payload under the same process/origin/even source sequence as mode/profile. P-ALH: authenticated immutable CP_INITIAL_STAGE → existing bounded lookup → clone-and-commit → existing snapshot. The source's `a75b68` registration and `be917e` initial memcpy establish this read binding; later `a75d10` updates use event lengths, not a fixed 256-byte contract. Update events and worker-time history remain unmodeled. This adds only ALH source knowledge: provider 3003 result-known remains **0/4**, no worker-known/gate-zero or six-field zero projection is published, and native capture remains false.

The focused verification below covers complete payload comparison after input poison/free, unchanged output tails, unknown initial ALH storage, missing/unsupported/wrong-length/truncated ALH entries, and a one-byte ALH mutation with recomputed BK4 checksum rejected by FNV. Every mutation preserves fresh and already-consumed owners atomically. File-loader failure/descriptor behavior is preserved. The original AArch64 libc 2.25 probe asserts known=1 and emits all 256 bytes for comparison with the authenticated source and payload SHA-256. Parameter-import, LIF capability and cache consumers are recompiled and checked, including their existing sanitizer and original-libc cases.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider runtime/analysis/test_cp_property_stage.py runtime/analysis/test_cp_property_stage_file.py runtime/analysis/test_cp_parameter_import.py runtime/analysis/test_cp_start_state_provider.py runtime/analysis/test_cp_start_state_data.py runtime/analysis/test_cp_owned_inputs.py report/lif-capability-owner/test_capabilities.py report/lif-cache-admission-contract/test_cache.py -q -ra
```

ALH verification result: **91 passed, no skips** (11 stage/file cases plus 80 connected cases). The system VM, full regression suite and observer/build integration are outside this extension.

## Reproduce and integrate

Run from `2026-10-17-qemu-native-camera`:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider runtime/analysis/test_cp_property_stage.py -q
```

Observed result: **8 passed**, including normal strict C11 and ASan/UBSan builds. The tests authenticate the complete installed public CP and ALLLANG files before slicing any stage, verify the stage SHA-256, then execute the real C owner against those exact bytes. They compare every retained profile byte and its SHA-256, not only context byte 4. All eight original CP windows (726 bytes) are rehashed. Host-only argument/guard tests need no assets; public-asset tests explicitly skip if either public file is absent. Locally all public inputs were available and none of the eight tests skipped.

For the connected provider/data regressions:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider runtime/analysis/test_cp_property_stage.py runtime/analysis/test_cp_start_state_provider.py runtime/analysis/test_cp_start_state_data.py -q
```

Observed connected-suite result: **16 passed**. Existing provider/data tests were read and run without modification.

The API is [cp-property-stage.h](../../runtime/analysis/device-models/cp-property-stage.h), implemented in [cp-property-stage.c](../../runtime/analysis/device-models/cp-property-stage.c). Link it with the existing `cp-start-state-provider.c` and `cp-start-state-data.c`. Runtime/build wiring belongs to the integrating parent and is deliberately outside this change.

| Operation | Contract and result |
|---|---|
| `cp_property_stage_init` | Caller-owned process-bound object; mode 3 from file initialization, property flags unknown, repository/base/origin unbound. No input pointers retained. |
| Host authentication | Verify full public CP, full ALLLANG and exact initial-stage SHA-256 using [source-pins.json](source-pins.json), then hold immutable stage bytes under the same external source lock as the guard. Merely passing an origin enum is not authentication. |
| `cp_property_stage_consume` | Requires the distinct `CP_PROPERTY_STAGE_SOURCE_CP_INITIAL_STAGE` tag, exact stage extent, origin VIRTUAL_SOURCE or HOST_TEST, matching PID and coherent even source sequence. Validates unfrozen header, BK4 structure, complete additive checksum, full-ID entries/attributes/payload bounds and exact FNV consistency. Commits all three properties atomically once. |
| `cp_property_stage_snapshot` | Copies the complete owned mode/property/profile/ALH binding at the exact consumed source sequence. HOST_TEST remains HOST_TEST. The sequence is a source transaction token, not a publication generation. A fresh object can be read with sequence 0 while all three properties remain unknown. |
| `cp_property_stage_deliver_profile` | Requires the same exact source sequence and origin; delivers the retained 256-byte context with all bytes known through `cp_start_state_provider_deliver_property`. A fresh callback-only provider retains `repository=0`, `property_delivered=1`, `property_bootstrapped=0`. Existing provider bootstrap metadata is preserved. This owner's readback separately records CP_PRIMARY. |

On actual public input, source mode byte `01` changes the owner's file-initialized mode from 3 to 1. The original mode consumer accepts only bytes 1/2; it does not turn other values into a new mode. Exact initial-stage identity makes modified bytes, including a fabricated mode 2 or changed profile value, invalid for this API. There is no general callback/key-setting framework. A later genuine mode/property callback would need a separate, source-backed event contract.

The adapter retains the three payloads and their source binding, not the 1.4 MB stage or an input pointer. Tests overwrite/free the input allocation before readback and delivery. Input capacity overlaps, pointer arithmetic wrap and typed-object alignment are checked. The caller must still supply accessible memory and serialize both owners; this is not a memory mapping probe or a concurrency primitive. Errors preserve the owner, provider and any output involved. No mode/property value from another source sequence is combined with the retained profile.

FNV-1a is a **noncryptographic consistency check**, not asset authentication. The C API intentionally relies on its public host loader for complete-file SHA-256 authentication. The Python test performs that authentication explicitly before selecting the stage; the C implementation adds no SHA dependency and cannot certify an arbitrary caller's claimed origin.

## Source evidence and repository identity

All source bytes use the single pinned public CP image: 18,090,880 bytes, SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`. The only image mapping is `CP_VA = raw + 0x108000` within `[0x108000,0x1248b80)`. BSS pointers are named storage dependencies, never file offsets. The eight exact windows and identities are machine-readable in [source-pins.json](source-pins.json). These implement the supplied completed source investigation; no fresh native CP run is asserted.

| Evidence | Original source / actual bytes | Observation |
|---|---|---|
| E-primary | `55dca4..55dd0c`, `55df9c..55e00e` | `55dca4 → 55dcc6 → 55df9c` supplies base `04000000` and initializes CP PRIMARY pointers `1a7e85c/60/64`. This is not a claim that ALLLANG file offset 0 aliases that address. |
| E-secondary | `be9bd4..be9cc8` | Optional secondary setup follows its own primary via `be9bd4/be9c64/55e014`; it is not a missing-key fallback in the primary consumer. |
| E-mode | `be90f2..be9130`, `40c278..40c2a8`, `eb5650..eb5664` | Mode lookup uses the same CP PRIMARY as profile. Only property bytes 1/2 replace the file-initialized mode 3 at `1107178`. |
| E-profile | `a48ba2..a48c08`, `110207c..110209c` | The unchanged full `01250006` ID/context registration reaches `55bf60 → be9130`; profile consumes context byte 4. The existing provider's parser/consumer source establishes full-ID lookup and payload decoding. |
| E-stage | Full public ALLLANG SHA-256, then exact `ALLLANG[ed000:]` stage SHA-256 and C readback | The explicit virtual CP_INITIAL_STAGE contains both full keys in section `0125`; mode payload is `01`, profile payload has 256 bytes and byte 4 is 0. |
| E-freeze | Exact initial stage, then only `stage[9]=1` | Stored checksum stays `09624557` while actual sum becomes `09624558`; frozen FNV is `a718b3aa73db052a`. Both fresh and consumed owners reject frozen bytes with `-EILSEQ` and preserve state. |
| E-host-tests | Commands above and new C self-checks | Strict/sanitized actual-source readback, input release, full payload identity, process/origin/sequence protection, atomic failure, legacy-primary refusal and blocked 16-byte reply. |

Reproduce E-primary through E-profile with `test_all_eight_original_source_windows`; E-stage with `test_exact_bk4_and_three_full_property_entries` and `test_authenticated_initial_stage_and_legacy_primary`; E-freeze with that C matrix and `test_freeze_is_a_different_invalid_initial_stage`. Original files stay at the relative public asset paths in source-pins, with hashes recorded there. E-host-tests does not constitute native CP runtime evidence.

| Stage field | Exact value |
|---|---|
| Full ALLLANG | 2,390,264 bytes; SHA-256 `3dab4f0d6b7790f4a7798034b57f43bfe3255c39dc6da2897fc288b3a218fe47` |
| Initial stage | File `ed000` to EOF, 1,419,512 bytes (`15a8f8`); SHA-256 `a90b46ae1d0fa054daeba321c52dc9d44d6bf32ca6eefcd1efb84fab2116e977`; FNV `5436a35ff036e6b5` |
| BK4 header | `+c="BK4\0"`, `+9=0`, sections=819, properties=33018, data=`31a20`, data size=`128ed8`, stored checksum=`09624557` |
| Tables | Section table at `100`, six-byte `{u16 count,u32 first}` entries; property table at `1432`, six-byte entries |
| Section `0125` | Stage `7de`, count=12, first=30964 |
| Full `01250003` | Entry `2e9fc`: `0000794b0701`; attribute 0; one byte at `74b79`, actual `01`; SHA-256 `4bf5122f344554c53bde2ebb8cd2b7e3d1600ad631c385a5d7cce23c7785459a` |
| Full `01250006` | Entry `2ea0e`: `0800824f07ff`; attribute 8; u16 size 256 at `74f82`; complete payload at `74f84`; SHA-256 `9814ef4bd1a406fdee481bc1d47f8c616030922d52d7b5f02747fe61a0401d66`; byte 4=0 |

The implementation follows BK4 header/section/property metadata and resolves all three complete IDs; the offsets above are independently checked evidence, not hard-coded payload access in the adapter. The old provider's reusable parser is private/static and outside this worker's edit ownership. The new adapter therefore repeats only a small bounded three-entry lookup with the same decoding, rather than calling the old SECONDARY_VIRTUAL bootstrap under a misleading name. If the parent later exposes a shared parser, this bounded helper can be replaced without changing source/repository identity.

F1 (`category=reverse_algo`, severity `n/a_re`, confidence high, evidence E-primary/E-mode/E-profile/E-stage/E-ALH/E-host-tests): the explicit initial-stage owner binds all three actual property payloads to one virtual CP PRIMARY source and transaction. F2 (`category=reverse_algo`, severity `n/a_re`, confidence high, evidence E-secondary/E-stage/E-host-tests): this does not identify ALLLANG file zero as native CP PRIMARY or authorize a fallback; the old primary returns `-ENODATA` unchanged. F3 (`category=reverse_algo`, severity `n/a_re`, confidence high, evidence E-stage/E-freeze/E-host-tests): the modeled frozen buffer is not a valid initial-stage input and cannot be silently repaired or consumed. These are implementation/source-content findings; native startup remains unverified.

P1 (`path_type=callflow`): authenticated complete public CP/ALLLANG (E-stage) → explicitly selected unfrozen CP_INITIAL_STAGE → modeled supplied base `04000000` / CP_PRIMARY (E-primary, F1) → same full-ID repository lookup for mode/profile (E-mode/E-profile) → one owned snapshot containing byte `01` and the complete 256-byte context (E-stage/E-host-tests) → existing callback consumer (F1). All provider result-ready/publication claims remain blocked. P2 stops before lookup for file-zero legacy primary or frozen input (E-freeze/E-host-tests, F2/F3).

## Failure behavior and remaining integration

| Error | Cause |
|---|---|
| `-EILSEQ` | Nonzero freeze byte, full BK4 checksum mismatch or wrong initial-stage FNV consistency, including recomputed-checksum mutations |
| `-EPROTO` | Invalid `BK4\0` marker |
| `-EMSGSIZE` | Wrong stage extent or wrong mode/profile/ALH logical length |
| `-EINVAL` | Invalid pointers/alignment/overlap/origin, malformed header/table/ranges or capacity overflow |
| `-ENODATA` | Missing exact full property key, or profile delivery before stage consumption |
| `-ENOTSUP` | Source tag other than CP_INITIAL_STAGE, or incompatible property attributes |
| `-EXDEV` | Forked/wrong PID or changed source origin |
| `-EAGAIN` | Torn, odd or nonquiescent source transaction |
| `-ESTALE` | Older consume sequence or read/delivery sequence different from the retained source transaction |
| `-EALREADY` | Repeated valid initial-stage consumption; the first owned binding is preserved |

The freeze flag is checked rather than excluded from checksum/hash. The adapter never changes `stage[9]`, refreshes its stored checksum or rewrites source bytes. Original post-freeze parser behavior has not been established. Integration must capture this exact authenticated initial content **before** a separate modeled freeze operation mutates its buffer, or supply a fresh authenticated initial copy.

Timeline: inspect the existing provider/guard and supplied mode source; publish the distinct early integration header; implement bounded atomic three-property consumption; verify exact public identities/eight original windows; run strict/sanitizer/content/error tests; document the source binding. The adapter remains available for explicit parent integration with default runtime policy unchanged.

M/C, Q, raw LIF, override, predicate kind, previous tuple/flags and fourth-result history remain separate source requirements. No fourth getter is called; only profile's predicate-known bit is established in a fresh provider. Tests verify result-known mask 0, absent LIF/ADJ/history consumption and ready/publication/AP bits 0, and preserve the blocked 16-byte 3003 reply. Mode is the separate CP mode source, not the data owner's M predicate. Parent runtime wiring, native startup history, hardware aliasing, UI behavior and capture are outside this bounded contribution.
