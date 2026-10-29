# Current functional graph evidence

[check_graph.py](check_graph.py) implements `evaluate(run, batch)` for **current-batch, same-run content proof of all thirteen virtual graph predecessors**. It reads the existing native messages, resource histories and strict UPM receipts. Historical accepted graph runs remain separate evidence; their logs, UPM events, SD exports and evaluation results are never fallback inputs.

**Implementation status: host-only module checks passed (45 tests, 637 subtests); current native graph acceptance remains unverified.** The earlier six leading-reason fixes, owner-role checks, slot-8 PinMem/kernel boundary and complete PIN_QUERY/Get join are preserved. This follow-up closes the complete source-defined OSD FORMAT_WRITTEN, OSD DMM request/reply and shared registry-native-free UIPC boundaries. The unchanged original `run-q2w2q6v8` now passes whole-console framing with nine provisional repairs; eight bind to exact records returned by existing pure content helpers, including all five repairs on the new boundaries. **The final content result remains FAIL:** the frozen six-edge verifier requires 14 sixth-edge internal frees but finds 13, so it never returns the earlier control-posthook record needed by the ninth repair. Full repair binding still refuses it. The unchanged failed receipt remains negative. `capture_verified`, physical ASIC compatibility, original CP execution/RAM and original RTOS verification always remain false. A future `graph_verified: true` means only that every implemented graph/provenance join passed on the explicitly supplied completed run and batch.

## Evaluate a completed current run

From the native-camera package root:

```bash
: "${RUN:?Set the absolute completed current functional run directory}"
: "${BATCH:?Set the absolute completed immutable unified batch directory}"
python3 -B report/functional-graph-evidence/check_graph.py "$RUN" "$BATCH"
```

`BATCH/ready.json` is also accepted. Both paths must be explicit, canonical, owned local paths. Input files must be regular, singly linked, owned, bounded and protected from group/world writes. Strict HDMI receipt validation additionally requires the actual direct `runtime/analysis/menu-runs/` run and binds its directory device/inode. There is no automatic run discovery or historical selection.

The CLI emits JSON to stdout and returns 0 only for graph acceptance, 1 for a structured negative verdict, or argparse’s 2 for bad arguments. There is no output overwrite option. The API returns the same JSON-serializable dictionary:

```python
result = evaluate(run, batch)
```

Call the API from a Python process started with `-B`. The unmodified historical helper imports use Python’s normal source loader; the wrapper refuses to import them when bytecode writes are enabled. It never changes that interpreter setting or any helper constants.

| Field | Meaning |
| --- | --- |
| `verdict` | `PASS`, `SOURCE/TRACE_MISSING`, or `FAIL`. |
| `graph_verified`, `all_13_graph_edges_complete` | True together only after all content, batch, image, current-run and immutability checks pass. |
| `all_thirteen` | Keys `"1"` through `"13"`; successful entries retain actual role messages and complete verifier transactions. All remain false on an incomplete result. |
| `native_verified_edge_numbers` | Exactly 1–13 on success; empty otherwise. |
| `dependency_hashes` | Current-batch SHA-256 for the entire explicitly required dependency closure below. |
| `evidence.batch`, `production_sources` | Actual ready, regression, ABI, source archives, selected observer, host model/build and exact current `source_paths` joins. |
| `evidence.public_image` | Whole retained selected-image digest and actual independently parsed public file bytes. |
| `evidence.content` | Actual edge transactions, original PID/TID, histories, resources and complete input audits. |
| `evidence.run_binding`, `run_files_sha256`, `console` | Same-run runner/UPM ownership, cleanup, raw/parsed digests and any individually joined transport repairs. |
| `missing[]` | Exact stage, `SOURCE_MISSING` / `TRACE_MISSING` / `EVIDENCE_INVALID`, and original exception/reason. |
| `capture_verified`, `physical_asic_compatibility_verified`, `original_CP_executed`, `original_CP_RAM_verified`, `original_RTOS_verified` | Always false. |
| `state_source` | `explicit-virtual-model-not-original-CP-RAM-RTOS`. |

The wrapper loads no model ELF and calls no VM, socket, network, hardware, physical SD, compiler, test runner or decoder. Original-image verification uses bounded private anonymous snapshots. It does not inspect private full-system assets, create media, acquire device locks or clean up another owner’s processes.

## Bind the actual candidate and production reference separately

The selected native/directory-SD QEMU is fixed to:

```text
a0d1bdd8a9aad822efe47f740a104972cac6ec1875265e8174b25349f54fee02
```

`backup_transport.binary_sha256`, its exact `manifest.files` entry, the actual file named by `backup_transport.binary`, the functional runner artifact and the same-run UPM watcher configuration must agree with that candidate. The candidate pathname is taken from the actual manifest; it is not forced to a historical run pathname.

The separate unchanged production reference is fixed to:

```text
e23589c44386c19417551c982e394b7a4e779f8e68a72f2964b705aca1e96c0d
```

Its actual file is checked at `runtime/sources/qemu-11.1.2/build-sony-ui/qemu-system-aarch64`. This hash is never substituted for the selected candidate. Arbitrary QEMU executables are refused.

The current capture checker’s original `check_batch()` combined these QEMU identities. This wrapper therefore uses its **low-level pure readers**, `frozen_sources`, `archive`, `digest_binding`, `typed_equal`, `uint`, `check_profile` and public library identities, with a local `check_current_batch()` joining the actual current receipt schema. It does not call or modify that checker’s `evaluate()` or `check_batch()`. The observer and media-preload ABI stdout/return codes, actual host regression count/log, actual compiler log, model source archive and actual ELF bytes are still required. Source counts are derived from the current source set, never pinned to 398 or another historical number.

The complete retained `selected-initramfs.cpio` must match the selected image’s actual manifest digest. Its bytes are parsed from the same private snapshot that was hashed. Every manifest-selected file is verified; additional public pins include ALLLANG seed `3dab4f0d…`, public CP artifact, fourteen unchanged original libraries (including original `dataflowInfraFramework.so` / `libInfraAvbbc.so`) and both original UPM/OSAL kernel modules. Conflicting manifest pins fail. The public CP artifact being present does not assert that original CP code executed.

## Content actually checked

Only existing content functions are reused:

| Content | Unchanged functions |
| --- | --- |
| Edges 1–6, full wire bodies, original AP identity/free, format forwarding, known payloads, DMM ownership/retirement and preserved caches | `evaluate-six-edges-native.py:verify_graph` and its `evaluate-five-edges-native.py` pure dependencies. |
| Edges 7–10 and 13, complete canonical Get retirements, ordered 64/64/72/56-byte handshakes and typed callback/event effects | `evaluate-graph-batch-native.py:verify_new_edge`, `verify_new_effects`. |
| Original Speech creation/caller history, original BB/ADF histories and complete full input audit bytes | `verify_legacy`, `verify_audits`, `tts_dmm_evidence.py:prove_initial_creation`. |
| HDMI11 prefix, driver, both UPM lifetimes, all 24 actual native condition receive/frees, original AP retirement, public Backup input | `verify_hdmi_edge.py:verify_hdmi_edge`, with its original strict `hdmi_upm_watch.py:read_receipts` and correlator. |
| OSD12 full DMM replies/requests, sixteen persistent resources, 48 ownership exchanges, sixteen notices, known masks, A5 unknown bytes, exact message frees and backing/cache divergence | `verify_osd_edge.py:verify_osd_edge`, passing the verified batch content module explicitly. |

Original role keys and dynamic caller SIDs are decoded again from each original complete 64-byte native request. Each edge must retain an actual 56-byte original AP free on the same observed PID/TID. Reconstructed model counts, provider publication, a ready flag or a separately authored success JSON cannot satisfy these checks. Graph-phase unsupported, unadmitted, fault, refusal or rejection records are retained and rejected, including late records.

The strict UPM reader must reconstruct the two original kernel lifetimes and mailbox commits from this run’s actual events. Its result and coordinator must show safe detach/debugger cleanup. The wrapper additionally joins watcher owner/QEMU PID and process generation, run device/inode, actual candidate digest, runner guest PID, the safely closed runner artifact, and the console digest at close. The first actual `functional-camera-broker-receipts.jsonl` binding must independently repeat the exact runner owner, QEMU identity, guest mailbox/model instance, run device/inode, candidate digest and both handoff sockets. That file is now a required bounded run input, hashed and re-read with the other unchanged run evidence. No historical UPM/broker event file is read. The parent must complete the existing HDMI watcher handoff before starting the functional broker; the checker observes the resulting ownership receipts and never performs that handoff itself.

### Host-control and runner are distinct roles

The current launch source establishes the chain:

| Source | Saved role/relationship |
| --- | --- |
| `menu_control.py:VM._run` | Sets `MENU_CONTROL_OWNER_PID=os.getpid()` and starts `run-menu-probe.sh`. |
| `run-menu-probe.sh` | Its normal path `exec`s Python `qemu-menu-probe.py`, retaining the direct child PID. |
| `qemu-menu-probe.py` | Copies the host-control PID into the manifest and creates `FunctionalCameraRunner` inside the probe process. |
| `functional_camera_runner.py:FunctionalCameraRunner.__init__` | Saves its own `/proc` PID, PPID, starttime and exact executable path. |
| `qemu-kernel-probe.sh`, runner `debugger_handoff`, broker `owned_config` | Launch isolated QEMU via the shell/bwrap chain; both live handoff/broker producers check actual descendant ancestry and `/out` run identity. |

`check_run_binding()` therefore accepts either an exactly identical owner PID/starttime or a runner whose saved **PPID equals the watcher/manifest host-control PID**. For the child case, host-control starttime must not follow runner birth; QEMU birth must not precede the runner. PIDs/starttimes are strictly typed and bounded. The exact owner executable path, handoff’s previous UPM result, QEMU PID/starttime/executable and the actual GDB socket device/inode must agree across their separate receipts. The actual broker binding must repeat every runner/QEMU identity field, including PPIDs. A matching executable name or an arbitrary PID is insufficient.

The `run-epi38kew` component-only read confirms host-control **443314 / 163486666**, runner **443543 / PPID 443314 / 163486697**, and QEMU **443579 / 163486825**. QEMU’s saved PPID **443578** belongs to the intermediate launch layer, so it must not be equated to the runner PID. The host-control generation is retained from the watcher and constrained by the saved parent/birth relationship; it is not a second independently logged host-control identity. Intermediate ancestors were checked live by the frozen producers but are not individually serialized in these receipts. This remains offline source/receipt consistency evidence, without a fresh `/proc` reconstruction or authentication against a rewritten receipt set.


No historical `evaluate()`, `verify_build()`, source-lineage baseline, SD check, EE snapshot, lock check or normalization function is called. The imported historical module’s startup pins only check its unchanged **pure dependency source files**, which must additionally be frozen in this current batch. These constants are neither rewritten nor monkeypatched. The OSD helper’s existing isolated `FunctionType` implementation remains untouched. The new early BB query check follows that existing pattern: it runs the unchanged `verify_get` body with a private owner/slot map and the source-defined BB outer reply SID expectation. Neither helper globals nor supplied wire bytes change; no function-text surgery is performed.

## Current raw-console interleavings

There is no historical raw SHA/offset table. `console_records()` retains the supplied raw console hash and can provisionally separate only:

1. The exact complete host vvfat `commit pending` / `commit complete` warning inserted into an actual labelled graph OBS record.
2. A complete guest record ending `capture_verified=0` immediately followed by one complete, grammar-checked `SONY_DFS_REQUEST` host record.
3. Only a complete `FULL_PINMEM_COMMIT` for canonical slot 8 / type 1 / dir 3 / index 0 / owner `0x90590818`, ending exactly `camera_startup_verified=0`, followed by one complete timestamped `UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022` kernel line and the guest's **already present empty CRLF line**. The kernel line is preserved independently. Missing guest CRLF, a nonempty suffix, another tag/key, partial kernel lines, noncanonical timestamps and any additional text fail.
4. A complete `PIN_QUERY` with exactly the source's ordered `tid`, `destination`, `source`, `bytes=48` and 96 lowercase hex `raw` digits, followed by the same complete UIPC kernel line and original empty CRLF. TID must fit the positive native PID range; SIDs are canonical nonzero 32-bit hex values, and the full 48-byte body must carry the producer's `0xa0a0a0a0` marker. Actual Get shape, key, caller, reply and retirement remain content checks. This rule does not admit `PIN_CONTROL_REQUEST`, arbitrary field order, extra/missing fields, other kernel warnings or partial payloads.

5. A complete `FULL_PINMEM_OSD_CONNECT_FORMAT_WRITTEN` with the exact ordered `create_format` fields, banks and ordinals 0–3, canonical native-width handle/addresses, unit `0xe1700`, extent 256, bounded `used`/`known`, two complete 16-digit lowercase FNV values and terminal `pixels=0`, followed by that same complete kernel line and original empty CRLF. Resource identity, mappings, SSOS/ETRY backing bytes, masks, counts and hashes still require the unchanged OSD verifier.
6. A complete `FULL_PINMEM_OSD_CONNECT_DMM_REQUEST` or `DMM_REPLY` with all ordered `wire_from` fields, positive native PID/TID, canonical SIDs/pointer, exactly 40 or 152 raw bytes matching `bytes`, and the complete terminal `virtual_local_transport=1 original_CP_executed=0 original_CP_pages_verified=0 frames_verified=0 capture_verified=0` flags. The same complete kernel/original CRLF rule applies. This grammar never supplies A5 padding, result bytes or source identity; the real verifier checks the complete request/reply, references and free history.
7. The complete shared `pin_registry_release` `FULL_<owner>_NATIVE_REPLY_FREE` printf for the actual `INFRABB`, `INFRAIMAGING`, `VEF`, `PINMEM`, `SCALAR`, `ADF`, `DRAWINFO`, `HDMIPIN` and `OSDPIN` registry names. Its exact ordered fields end `lease=<positive-u64> bytes=56 rc=0`; PID-range sender/TID, canonical SIDs/pointer and the same kernel/original CRLF are required. Actual same-thread/sender/waiter, destination, pointer/lease and ordered Get retirement remain content requirements. A parsed free outside the real helpers' returned proof still cannot join.

The third rule follows the full `pin-registry-core.c:pin_registry_dispatch` COMMIT `snprintf` and `menu-observe.c:record` console-write format. The fourth follows the complete `menu-observe.c:osal_snd_msg` `PIN_QUERY` printf and 48/64-byte marker guard, with the same console writer. Rules five and six follow `device-models/pinmem-osd-connection.c:create_format` / `wire_from`; rule seven follows `device-models/pin-registry-core.c:pin_registry_release`. The GPL producer was checked directly at `linux-kernel/drivers/udif/cdev.c:100` → `include/linux/udif/macros.h:UDIF_CALL_FN` / `UDIF_PERR`, with `kernel/printk/printk.c:print_time` supplying `[%5lu.%06lu] `. Only that complete warning body is supported, within the complete 1024-byte boundary budget and the source integer bounds. The parser checks the original raw kernel slice and the original guest CRLF slice before moving the line ending; it inserts **zero framing or guest payload bytes**. Existing vvfat reconstruction remains limited to eight warning insertions per record and 16384 reconstructed bytes; the whole-console read remains bounded by `MAX_LOG`. Every warning and kernel-boundary repair retains the exact reconstructed record and requires `bind_repairs()` content consumption. The ledger retains separate kernel and guest-ending raw ranges, kernel text, reconstructed record/SHA and parsed line. No other kernel diagnostic is filtered or generalized.

For a repaired early BB query, `check_repaired_queries()` adds the unchanged real `verify_get` result to `repaired_early_BB_Get_joins` before the final repair binding. Its private map contains all **21 canonical keys/slots** from `infrabb-registry.c`, including data, control and DrawInfo tuples; it does not select a historical slot or byte offset. BB's own outer reply SID is explicitly `0x9284074a`, as set by `.reply_sid=NATIVE_INFRABB_CP` and observed in the actual 56-byte reply. A zero SID fails. The query must be the exact returned `original_AP_query`, on the graph's observed AP TID, with its full opaque original request bytes preserved. Request, reply, slot/type/dir/index/state/owner/status, pointer/lease and same-sender native 56B free must agree and precede both the next pin send and the first graph request. Duplicate/missing Gets and borrowed record joins fail. Repaired queries for other owners must already be returned by an existing real graph Get verifier; the BB extension cannot consume them. Host send `rc=0` is never a native free.

All guest payload bytes come from the supplied current console. Field validation applies to the graph families in `GRAPH_ROOTS` plus `PIN_QUERY` and `PIN_CONTROL_REQUEST`; unrelated OBS diagnostics are preserved without interpreting their free text. Within graph records, only the exact leading tag/reason combinations in `GRAPH_BARE_REASONS` are recognized before validating the remaining `key=value` fields. Reasons remain in the original record bytes; no field is invented. Duplicate fields, unknown bare tokens or warnings, truncated records, ambiguous host content or unexpected field syntax still fail. Required fields and their values remain subject to the unchanged content verifiers. Each repair retains its actual raw offset or record start, complete host diagnostic, reconstructed record, parsed line and reconstructed SHA. **Acceptance also requires that this exact reconstructed record be returned by an actual content verifier.** A repair outside that verified subset is refused; it is never accepted merely because the reconstructed record parses. Standalone host warnings are preserved. No repaired log is written to disk.

This intentionally supports a finite transport grammar. A different current interleaving, or an interrupted record outside the content functions’ returned evidence, is a precise negative result requiring additional producer evidence or a new tested join. It is not silently cleaned up.

## Freeze the complete explicit dependency closure

Before the parent runs the whole unified regression/build/ABI batch, include this component and all paths below in the actual `inputs.json` groups and `inputs.tar.gz`. Paths are relative to the native-camera package root; `FROZEN_DEPENDENCIES` in the code is the authoritative machine-readable list.

```text
report/functional-graph-evidence/check_graph.py
report/functional-graph-evidence/test_graph.py
report/functional-graph-evidence/README.md
report/functional-camera-evidence/check_evidence.py
report/functional-camera-evidence/test_evidence.py
report/native-card-write/check_writeback.py
report/capture-evidence/check_evidence.py
report/cp3006-start/verify_public_seed.py
runtime/analysis/backup_profile.py
runtime/analysis/initramfs_identity.py
runtime/analysis/tts_dmm_evidence.py
runtime/analysis/hdmi_upm_watch.py
runtime/analysis/build-functional-camera-model.py
runtime/analysis/functional_camera_broker.py
runtime/analysis/functional_camera_runner.py
runtime/analysis/snapshot-observer-sources.py
runtime/analysis/scratch/validate-unified-camera.py
runtime/analysis/scratch/evaluate-graph-batch-native.py
runtime/analysis/scratch/evaluate-six-edges-native.py
runtime/analysis/scratch/evaluate-five-edges-native.py
runtime/analysis/scratch/verify_hdmi_edge.py
runtime/analysis/scratch/verify_osd_edge.py
```

The dynamic `groups.production` must additionally equal the current exact `snapshot-observer-sources.py:source_paths(RUNTIME)` mapping, including its report metadata inputs. The observer archive, ABI source count and every source SHA must agree with it. Functional builder/broker/runner must occur specifically in `groups.host`. All frozen sources and same-run evidence bytes are checked again before success. This worker changes only this directory’s three new files; the parent owns the validator’s component/extra-input list and capture-checker integration.

For integration, call `evaluate(run, batch)` and require `graph_verified is True` plus `all_13_graph_edges_complete is True`. Retain this entire result in the parent’s evidence. Do not promote its capture flag, reuse a historical success result, or remove an existing predecessor blocker solely because the wrapper source now exists. Current acceptance still requires an actual completed run.

## Host checks and known limits

The module-only host check completed with **45 passed, 637 subtests passed**:

```bash
python3 -B -m pytest -p no:cacheprovider --import-mode=importlib \
  report/functional-graph-evidence/test_graph.py -q
```

Real content functions check complete native wire bodies, opaque original request padding versus zeroed model padding, source/key/status corruption, actual AP TID/56-byte-free mismatch, all 24 condition bodies/leases, a missing UPM receipt, OSD persistent reference corruption, copied DMM request-as-reply, backing/cache differences, duplicate/truncated records, current warning reconstruction, late unsupported records, unfrozen/changed helper source and new-input/old-ready-hash mismatch. The six actual leading-reason regressions remain intact. New HOST_TEST fixtures exercise parent/child and same-process owners, shell-parent QEMU, incorrect PPIDs/PIDs/generations, exact independent broker identity/socket/run/mailbox mismatches, unsafe cleanup and missing broker input. A complete native-format Get fixture sends the repaired slot-8 COMMIT through the unchanged real `verify_get` body with the existing OSD slot extension and then `bind_repairs`; malformed guest/kernel bytes, suffix/position/line interruptions, integer/timestamp bounds and missing or mismatched consuming records still fail. The full thirteen-edge orchestration positive uses explicit mocks and never asserts native or `evaluate()` acceptance. The OSD rejection scaffold remains deliberately incomplete. No historical run is used as a new-run positive. No full regression, build or VM was run.

The PIN_QUERY regressions additionally compare the complete source printf/marker guard/console format and all 21 source BB slots, exercise canonical slots 1, 7, 10 and 20 with distinct typed tuples and nonzero opaque original bytes, and pass the reconstructed records through the unchanged real `verify_get` body and final `bind_repairs`. A separate PinMem slot-4 query proves that another owner requires its existing actual Get consumer. Negatives cover malformed/duplicate/missing/truncated fields, noncanonical or oversized integers/SIDs, wrong kernel bytes/timestamp/terminator, missing/duplicated query/request/reply/commit/free, wrong key/slot/status/source/lease/TID, zero BB reply SID, host-only send, another record's line/raw, a Get after graph start, and warning/read/record budget overflow. Eight exact vvfat insertions remain accepted; nine fail. The existing short/incomplete OSD FORMAT_WRITTEN and DMM_REPLY negative fixtures remain rejected, with their original assertions preserved.

A separate complete **HOST_TEST** OSD fixture covers constructor/resource guards, distinct opaque original Get padding, both real Get retirements, all sixteen `(bank, ordinal)` resources, 48 complete DMM requests/replies in both 40/152-byte formats, sixteen notices and 114 internal message frees. Every one of its 112 format/DMM rows receives a complete kernel boundary plus an exact vvfat insertion, giving 224 repairs. The unchanged `verify_osd_edge` returns those actual Log objects and `bind_repairs` joins every repair. These are synthetic producer-format fixtures, not native acceptance. Source printf assertions bind both full grammars; corrupt hashes/masks, DMM A5 padding/result/body, source/TID, resource references, missing/duplicated rows/frees, AP 56-byte free, predecessor/identity or a borrowed line/raw record all fail the real consumer. Shared registry-free fixtures similarly join actual Get/free records and reject wrong sender/waiter/destination/lease and unknown/incomplete/oversized syntax. All old tests remain present; no DSO/C build or original log mutation is involved.

### Current successor: run-q2w2q6v8

The original failure receipt records `FAIL / console_framing / ValueError: malformed OBS field: 1418.871426]`. The actual complete producer is **PIN_QUERY**, not another PinMem COMMIT slot:

```text
OBS PIN_QUERY tid=382 destination=0x9284074a source=0x81cf61c4 bytes=48 raw=c461cf81a0a0a0a001003000180000003000000000000000001000001800020000000000010000000100000000000000
```

The raw mixed window is `[1119681, 1119926)`, kernel `[1119853, 1119924)`, and original empty guest CRLF `[1119924, 1119926)`. The full mixed window hashes to `97e23a8fd285e986fab1ec511405d6b7d9219bcc249a20c3958ac317cb91d71a`; the reconstructed payload SHA-256 is `1a5d0a2e7d86cdbecfe7559fcf196639f20101b1a9a1754852fc2da50889b885`. These are documentation of read-only observations, never parser lookup keys.

A component-only read through the complete first graph REQUEST (raw prefix length 1123126) passes the actual repaired query through `check_repaired_queries()` and `bind_repairs()`. It joins AP PID/TID **258/382**, caller `0x81cf61c4`, key `(0,1,1,0x9284074a)`, slot **1**, reply `0x7fae0c6ac0`, lease **3**, the actual 56-byte reply with BB outer SID, and the original same-thread free (`tid=sender=382`, `waiter=1`, `bytes=56`, `rc=0`). This is one component's actual native-message consistency check; it does not evaluate the old frozen batch or establish all thirteen graph edges.

The original next **framing** blocker was `ValueError: malformed OBS field: 1522.508050]`. Its complete source producer is `pinmem-osd-connection.c:create_format`'s `FORMAT_WRITTEN` printf, whose raw payload is:

```text
OBS FULL_PINMEM_OSD_CONNECT_FORMAT_WRITTEN bank=1 ordinal=3 handle=0xe1000017 unit=0xe1700 extent=256 physical=0x500010700 cp_alias=0x81000700 used=80 known=78 fnv=d62d71d3a85d13fb known_fnv=e4354ec8e8ebffcb pixels=0
```

The complete raw window is `[1391215, 1391571)`: exact vvfat pending warning `[1391431, 1391498)`, kernel `[1391498, 1391569)`, guest CRLF `[1391569, 1391571)`. Its full mixed-window SHA-256 is `8a845ac0da011a8c418b67f8db7749a4de3b068201bafd3f5575dc78a520f300`. The kernel is `[ 1522.508050] UDIF: cdev_ioctl() Line 100: uipc: warning ret = -1022`. This record now passes the complete source grammar, unchanged actual `verify_osd_edge`, and `bind_repairs`; reconstructed payload SHA-256 is `6e37f3a407dad5c8159a0dea858ca3bf9695226420838d0c68839efc481846be`.

The same whole-console pass closes both later complete boundaries without adding guest bytes:

| Producer / parsed line | Original raw ranges | Content consumption |
| --- | --- | --- |
| OSD `FORMAT_WRITTEN` / 14464 | Whole `[1391215,1391571)`, kernel `[1391498,1391569)`, guest CRLF `[1391569,1391571)` | Returned resource `written`, bank 1 / ordinal 3, handle `0xe1000017`, actual SSOS/mask hashes. Both warning and kernel repairs join. |
| OSD `DMM_REPLY` / 14607 | Whole `[1425165,1425785)`, kernel `[1425712,1425783)`, guest CRLF `[1425783,1425785)` | Returned DMM exchange reply, op `0x21`, token `0x4f2c`, reply SID `0x6100e8`, handle `0xe100001e`, complete 152 bytes including unchanged A5 padding. Kernel timestamp `1531.715414`. |
| `HDMIPIN_NATIVE_REPLY_FREE` / 14660 | Whole `[1436422,1436708)`, warning `[1436568,1436635)`, kernel `[1436635,1436706)`, guest CRLF `[1436706,1436708)` | Returned audio-edge canonical HDMI Get free, `tid=sender=382`, `waiter=1`, actual pointer `0x7fae0c39c0`, lease 4, bytes 56, rc 0. Both warning and kernel repairs join. |

The DMM whole-window SHA-256 is `a50f132b3fca4314411292c0c1d51e1f4a08751e472f5a969e9c46f6fa737d2e`; the native-free window hashes to `554e67a265634d63c848dae50491fa761628a34bea3982b6a97a73f0f63d9894`. These offsets/hashes are observations, never parser allowlists.

**E-q2 / F-q2 / P-q2: final bounded result.** The 2,068,040-byte original console passes framing into 2,067,703 bytes with **nine provisional repairs**; parsed SHA-256 is `7a5160dc5e9471b8c40caea45ee6ece1840050dfd3c8bfa2f8d706593f0dbb94`. Kernel lines and graph-external diagnostics remain present independently. Existing pure `verify_legacy`, `verify_new_edge`, `verify_osd_edge` and `check_repaired_queries` component calls return the exact six reconstructed records covering eight repair ledger entries for binding. The unchanged real OSD call verifies sixteen resources, 48 DMM exchanges, all reference/open/mask/backing effects, all message frees and the actual two Get retirements. No full-run acceptance follows from these components.

The ninth entry remains **unjoined**: vvfat warning at raw offset **1138864**, reconstructed parsed line **12661**, tag `FULL_IMAGING_CONTROL_CONNECT_POSTHOOK_NO_FORMAT`. Its bytes are retained. The function that owns/returns that posthook, `evaluate-six-edges-native.py:verify_graph`, aborts at the sixth edge:

```text
EvidenceError: ('FULL_VEF_PINMEM_INPUT_CONNECT', 'internal free count', 13)
```

That frozen function requires **14** sixth-edge internal frees and observes **13**. Consequently `check_graph_content` fails before its thirteen-edge proof can return the posthook; `bind_repairs` on all nine also refuses `repaired record lacks an actual content-verifier join`. There is no missing final field to infer and no additional framing boundary left in this original console. The final whole-content verdict remains **FAIL**. No free record, padding, source role or causal prerequisite is supplied to bypass it.

To reproduce this read-only component result from the package root, with the original q2 logs locally available (it emits no receipt and never calls `evaluate()`):

```bash
python3 -B - <<'PY'
import runpy
from types import SimpleNamespace

g = SimpleNamespace(**runpy.run_path('report/functional-graph-evidence/check_graph.py'))
run = g.RUNTIME / 'menu-runs/run-q2w2q6v8'
raw = g.read(run / 'console.log', g.MAX_LOG)
parsed, repairs = g.console_records(raw)
# Current helper source identity only; this is not a completed-batch check.
frozen = {str(g.NATIVE / n): g.sha(g.read(g.NATIVE / n)) for n in g.FROZEN_DEPENDENCIES}
b, hdmi, osd = g.load_content_helpers(frozen)
log = b.Log(parsed)
identity = tuple(log.one(osd.PREFIX + '_REQUEST')['fields'][k] for k in ('pid', 'tid'))
first = log.one(b.six.SPECS[0][0] + '_REQUEST')['line']
proof = {'identity': identity, 'edges': [{'REQUEST': {'line': first}}],
         'legacy': b.verify_legacy(log, identity, first)}
previous = log.one(b.six.SPECS[-1][0] + '_REPLY_FREE')['line']
for spec in b.NEW[:-1]:
    edge = b.verify_new_edge(log, spec, previous, identity, first)
    proof[spec[0]] = edge
    previous = edge['REPLY_FREE']['line']
edge = osd.verify_osd_edge(log, log.one(hdmi.PREFIX + '_NATIVE_REPLY_FREE')['line'], identity, first, b)
proof['OSD_component'] = edge
proof['audio_component'] = b.verify_new_edge(log, b.NEW[-1], edge['REPLY_FREE']['line'], identity, first)
proof['early_BB_Get'] = g.check_repaired_queries(log, repairs, proof, b)
print('framing:', len(raw), len(parsed), 'repairs:', len(repairs), 'parsed_sha256:', g.sha(parsed))
for repair in repairs:
    try:
        g.bind_repairs(proof, [repair])
        print('component JOIN:', repair['parsed_line'], repair['kind'])
    except ValueError as error:
        print('UNJOINED:', repair['parsed_line'], repair['repaired_record'], str(error))
try:
    g.bind_repairs(proof, repairs)
except ValueError as error:
    print('whole repair bind FAIL:', str(error))
try:
    g.check_graph_content(log, run, b, hdmi, osd)
except ValueError as error:
    print('whole graph content FAIL:', str(error))
assert g.read(run / 'console.log', g.MAX_LOG) == raw
PY
```

The callflow is raw console → finite producer grammar → original-CRLF byte move with kernel preserved → real content helper's returned Log object → exact line/raw repair binding. The residual risk is the rejected sixth-edge message-lifetime evidence and absent completed-current-batch/full-graph proof. This closes the requested framing investigation for this console; it does not chase or repair the separate sixth-edge content contract.

Original read-back SHA-256 values remain unchanged:

| Original input | SHA-256 |
| --- | --- |
| `menu-runs/run-q2w2q6v8/console.log` | `1a09a3b29964b532ee2e451c6852219d604b000caf6eb1c3dcd17f79e18a01ef` |
| `scratch/functional-graph-run-q2w2q6v8.json` | `8eb14fc9e9656347e0c98b0f6f4e71bccdec10f22ba8e4ac7f9af299d43da5f3` |
| `scratch/unified-camera-uwy36pb3/ready.json` | `048fda169b5f825e375928d7bc4e2691688b5321e7d0bec33866bdfce2eb8780` |
| `scratch/unified-camera-uwy36pb3/inputs.json` | `5a1f97045e0b24830d0444ab99231bc28f1d8ed7e2fc32f03df38b8ca3276b41` |

Paths in that table are relative to `runtime/analysis/`. The three component files now differ from the old frozen batch; this check did not rewrite hashes, invoke `evaluate()` against it, create a new success receipt, run a full regression/build/ABI/VM, or inspect a private dump. The parent owns the next joined batch and actual VM. Capture and physical compatibility remain false; the existing run still has no JPEG/MP4 product.

### Historical leading-reason failure and earlier strict rejection

The unchanged `runtime/analysis/scratch/functional-graph-run-epi38kew.json` records `FAIL` at `console_framing` with `ValueError: malformed OBS field: predecessor-or-new-cold-Get-free-not-ready`. Parsing the actual console row reproduced that exception before the fix:

```text
OBS FULL_SCALAR_CONNECT_UNADMITTED predecessor-or-new-cold-Get-free-not-ready requests=0 faults_unchanged=1
```

This row and its ADF/DrawInfo equivalents **are required early graph refusal evidence**, consumed by `verify_new_edge()`. Filtering them would lose the early/late refusal distinction. `device-models/pin-peer-connection.inc` emits the literal reason first, followed by `requests` and `faults_unchanged`. The narrow parser change recognizes that exact leading literal only for those three tags. It also recognizes the actual HDMI/OSD `_UNADMITTED` and HDMI `_STATE_PENDING` literals emitted by `pinmem-hdmi-video-connection.c`, `pinmem-osd-connection.c` and `hdmi-video-state.c`. All six records retain their original bytes and fields. Arbitrary reasons and reason literals in transaction messages are still rejected. Message lengths, source/IDs, original AP thread, ACK/free, resources and thirteen-edge causality checks are unchanged.

At the end of c062, a read-only framing check advanced past those reason records, then rejected `ValueError: malformed OBS field: 1515.781307]`. This follow-up proves only that specific complete PinMem/UIPC boundary. In the unchanged actual console (zero-based byte offsets), the complete mixed window is `[1349257, 1349614)`: the exact 67-byte vvfat warning occupies `[1349293, 1349360)`, the complete kernel line `[1349541, 1349612)`, and the guest's original CRLF `[1349612, 1349614)`. Removing only the established vvfat insertion and moving that existing CRLF yields the original COMMIT payload ending `camera_startup_verified=0`, with reconstructed record SHA-256 `185d9d1b22e14eae75b51b53d5103bca9c349f386dd12abcd22c0cebf006fe54`; the entire kernel line remains separately present.

A subsequent parent correction keeps graph-external records entirely uninterpreted: the vvfat insertion at raw offset **1468055** in `NATIVE_CP_CAPTURE_FORMAT_DIAGNOSTIC_REPLY_FREE` is preserved byte-for-byte, with no repair entry and no content claim. Graph-scoped warning reconstruction and all required graph fields remain strict. The unchanged whole console now passes a **framing-only** scan with seven provisional graph repairs; this does not prove full-run consumption. No full-run `bind_repairs`, native `evaluate()` acceptance or successful receipt is claimed. The complete original console still hashes to `6ea73abfa6d0602f12571a0aeeb1257e6bca159e17a2b7e8452dcd844573e81e`.


The actual console SHA-256 (`6ea73abf…`), original failed receipt (`6c68b7e5…`), frozen batch `ready.json` (`f36f01c1…`) and `inputs.json` (`ee0b906a…`) were read back unchanged. Frozen batch `unified-camera-d5lt_67f`, actual `run-epi38kew` and all original failure receipts remain untouched. The three edited component files now differ from that batch's frozen hashes; a current `evaluate()` must reject the old closure rather than treating this host test as new batch acceptance. No full native evaluation or new successful receipt was produced.

This fixes the checker's known reason grammar, owner-role error and one fully supplied PinMem/kernel boundary. It does not establish graph success or repair original capture: this run has no JPEG/MP4 product; **`3003 start_complete=1` was actually emitted**, while `mode1` was not emitted. `capture_verified` remains false. Existing unchanged helper tests retain responsibility for their broader C/native fixture coverage.

Evidence is plaintext consistency evidence. SHA-256 binds file bytes and FNV retains compatibility with existing content observations; neither authenticates the observer or a maliciously rewritten receipt set. Some existing helpers explicitly rely on the frozen C implementation for event-body readback or aggregated final OSD backing readback, and label missing standalone runtime bytes in their returned evidence. Their results are kept intact, not strengthened into independent raw CP/RTOS/hardware proof. Graph proof does not include SD/media capture, CMOS pixels, encoding, GPE readiness, camera EE or a normal CP mode transition.

## Evidence → finding → path

| Evidence | Finding | Implementation |
| --- | --- | --- |
| Actual unified `ready`, regression/ABI receipts, source archives, model compiler receipt and observer build index | Current graph content must be tied to the exact tested source closure; historical observer/test pins cannot establish that join. | `frozen_inputs`, `check_current_batch`, `check_production_sources`, `check_dependency_hashes`. |
| Actual candidate manifest/file digest and separate production reference | Selected `a0d` and unchanged `e235` are distinct roles. | `check_qemu_files`, `check_run_binding`. |
| Same-run original full messages, actual AP frees, DMM/format/native UPM/condition/OSD histories | All thirteen predecessors have content/lifetime requirements beyond counters or ready flags. | `check_graph_content`, `check_role_messages` and unchanged pure verifiers listed above. |
| Saved host-control PID, watcher identity, runner `/proc` identity and first same-run broker binding | Host-control and its probe/runner are valid parent/child roles; exact runner/QEMU generations and sockets require independent receipt joins. | `check_run_binding`; source chain and generation limits above. |
| Actual raw mixed console bytes plus exact returned verified records | Current transport repairs require a fresh content join, never an old offset or SHA table. Complete OSD format/DMM and registry-free boundaries now join their real helpers; q2 framing passes with nine repairs, eight join, and the earlier control-posthook repair remains refused because the frozen sixth-edge content check aborts at 13/14 internal frees. Graph-external diagnostics stay raw. | `console_records`, `parse_record`, `check_repaired_queries`, `bind_repairs`; E-q2 → F-q2 → P-q2 above. |

Scope follows the local isolated public-package functional simulation authorization in the project [AGENTS.md](../../../../../../AGENTS.md). No VM, network, physical device/SD, private dump, firmware write, commit or publication was performed for this component.
