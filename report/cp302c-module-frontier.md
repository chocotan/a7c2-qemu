# CP302c module consumer frontier

**The module-2 queue boundary is source-closed; its command effects are still open at `8c736a`.** It can be implemented independently as a real borrowed-context/owned-queue operation, but cannot yet publish successful `0323`, `032c`, or `0302` completion. No existing graph backend consumes this operation. `original_cp_verified=false`, `302c_native_verified=false`, `frames_verified=false`, `capture_verified=false`.

Scope: authorized offline inspection of the public ALLLANG CP/AP originals and current backend source. No VM, socket, network, camera, private/full-system input, production C/H edits, or delegation. Initial central state 6 versus 8 and Backup/A513 state history belong to [the separate state report](cp302c-state-frontier.md). Parent evidence selects variant 0 if the 8→7d branch is entered; that does **not** select initial state 8. The parent's `run-ouc1t64_` thirteen graph connections remain valid separate results.

Evidence E1 is [the small byte-pin file](cp302c-module-source-pins.json), including per-window SHA-256, exact original bytes, and raw offsets. CPVA = raw + `108000` for file-backed CP code/data only; this subtraction does not apply to CP RAM. CP: 18,090,880 B, SHA `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`. AP SHA `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`. The existing eight transition windows are reused by reference with their file hash; this investigation does not repeat their chain derivation.

## Actual completion predicate and module ownership

Finding F1 (`n/a_re`, high confidence, E1: `b1f3ae`, `b1f3ce..e4`, `4b2b54`): M=`1a52a88` contains requested u16s at `+18+2*slot` and returned/observed u16s at `+32+2*slot`. A descriptor word's high byte selects slot=(high-1). The terminator's selected bits require **full u16 equality**, not an accumulated callback count. An observed word is published by the original worker's `4dab22..4dacf0` tail; a cleanup callback only clears occupancy. Parent all13 graph success provides neither these words nor this worker receipt.

| Slot / mask bit | Known 6→77 request | Normal observed u16 source in original worker | Actual producer identified here |
|---|---|---|---|
| 0 / 0001 | `011a` | `(G+0c)->+ba4` | Common preparation: `4ba624` decodes 12B table entry, `4d7c64..70` copies it to P+19b0. Full effects/publication remain open. |
| 1 / 0002 | `0202` | `(G+44)->+14` | `4d9b00 → 991e12`, c8B view and five-word record; worker `39e498`. |
| 2 / 0004 | Not updated by this 6→77 descriptor | `(G+10)->+0` | `4d9ac2 → 8c9846 → 8c6d02`, worker `8c6d86`; required in the parent's variant-0 8→7d path. |
| 3 / 0008 | `0405` | `(G+48)->+0` | `4d9b84 → 74c216`, N=c8B snapshot, completion record, module=3. |
| 4 / 0010 | `0502` | `(G+38)->+0` | `4d9c88 → b3a436`; saves record and module=4, posts `504d64` work. Full effects unclosed. |
| 5 / 0020 | `0602` | `(*G)+0e` at `4dacc4..cc` | `4d9c08 → aea568`, module=5; normal pointer view copied c8B. Root-valued observed source alone is not evidence the work finished. |
| 6 / 0040 | `0702` | `(G+50)->+0` | `4d9bc6 → 934338`, c8B view, completion record, module=6; posts `9343bc`. |
| 8 / 0100 | `0920` | `(G+20)->+0` | Normal completion source identified at `4dabe0..fa`; exact producer/work contract remains unclosed in this bounded pass. |

`017b` selects 0,1,3,4,5,6,8 (seven source-loop comparisons). `017f` also selects slot 2 (eight). The known 6→77 sequence remains `011a 0202 0405 0502 0602 0702 0920 0a00 0b10 0c02 0d00 817b`. For the parent's source-selected variant 0 **conditional on state 8**, module 2 goes through `0323`, boundary `8004`, then `0302`, final `817f`; the alternate variant with `032c` is distinct. See the separate state report for exact descriptor order and selection evidence. Do not generalize the no-module-2 variant `817b` to variant 0.

G=`173efe8` is the original pointer view; P=`172fe50` is the working object. `b2ebce` binds `N+0=P`, `+04=P+d68`, `+08=P+dc0`, `+0c=P+e18`, `+10=P+2950`, `+14=P+3930`, `+18=P+3cb0`, `+1c=P+3be8`, `+20=P+3d48`, `+24=P+39ec`, `+28=P+39dc`, `+2c=P+3d58`, `+30=P+3d74`, `+34=P+3e80`, `+38=P+41c8`, `+3c=P+4330`. `b2e8e0` binds independent published pointers `+40=*(P+4e3c)`, `+44=*(P+4e40)`, `+48=*(P+4e44)`, `+4c=*(P+4e48)`, `+50=*(P+4e4c)`, `+54=*(P+4e50)`, `+58=*(P+4e54)`. These are CP pointers/fields, not AP instances or graph-owner pointers. No supported mapping from these worker domains to the eleven new graph backend owners is proved; assigning VEF/ADF/HDMI names from numerically matching commands would fabricate ownership.

The diagnostic override mask at `1a533a4+8e` can select requested root words instead of the normal observed sources. This report records that branch to prevent accidental use. It is not a valid way to establish module consumption.

## Family 1 phase 1/3 observer bindings

Finding F2 (`n/a_re`, high confidence, E1): aggregate S=`1a52b38` constructs family 0 at S+ac and family 1 at S+dc; family 1 vptr is `e77b40`, handler `+18=4b4cf1` (Thumb pointer). Generic `b2015c` does observer phase 1 → handler vtable+18 → observer phase 3. The observer pointer is S+34. `b208ba` invokes vtable+8 on S+34 and S+54, in order.

| Object | vptr / callback | Binding from `b1fd1c` and helper | Event 32d selection |
|---|---|---|---|
| A: S+34, ExecSleepTrans | `e77cf0`, +8=`b212b9` | A+0c=S+108 request actor, +10=S+154, +14=S+5d4 exec handle | `b214d2..e2`: phase1 index8, phase3 index5. Table `e77cfc`, 9 pairs/state, 7 states. |
| B: S+54, ExecExpFocusTrans | `e77bd8`, +8=`b20e83` | B+0c=S+108, +10=S+13c, +14=S+5d4 | Phase1 index5. Phase3 normally5; if exec handle active and `b22024 → b1f140(3024)` admits the separate transition, index3. Table `e77be4`, 6 pairs/state, 5 states. |

Each pair is the ARM member-pointer pair `(function-or-vtable-offset, this-adjustment)`; preserve both. For A index8 all 7 pairs are (0,0). A index5: states0/1/2/4=(0,0), states3/6=(b21357,0), state5=(b21419,0). `b21356` is diagnostic state/index printing; state5's `b21418` is business work through `b222b2` and a state change to6, so phase3 cannot globally be erased. For B index5 all5 pairs are (0,0); B index3 is (0,0) in state0, (b20f11,0) in states1/4, (b20f5b,0) in states2/3. `b20f5a` initiates additional state work via `b211a4`. The selected pair/index writes themselves are observable effects even when the pair is zero. Live A/B states and 3024 admissibility remain unobserved here; no RAM page is assumed zero.

## First parallel implementation boundary: slot 2 queue operation

Finding F3 (`n/a_re`, high confidence for queue ABI, incomplete for business effects, E1): implement a dedicated CP slot-2 operation with source signature **`8c9846(N, completion_record, module=2)`**, where the thunk branches to **`8c6d02`**. This is an internal C/RTOS work API, not an AP request addressed to ADF and not a twelve-byte reply.

The actual caller `4d9a82..4d9ac2` checks the separate root/P+19ac suppression bit2. When it schedules work it sets busy[2] at `1a6a824` to1 and passes N=`1a6a85c`, all 200B/50 little-endian pointer-view bytes, and a 20B completion record. Known record words are `[637075,0,4de191,0,0]`; exact bytes are **`757063000000000091e14d000000000000000000`**. The separate module u32 is **`02000000`**. The actual 200B runtime view, pointed-to data, suppression bit, prior banks and selector are unknown in this offline inspection; none may be zero-filled. For a real accepted input, root slot-2 word at `(*N)+6` must retain **`2303`**, **`2c03`**, or **`0203`** as appropriate to the current descriptor step. These are little-endian u16 words, not the external ADF payload bytes.

| Step | Original source contract / actual owned effect |
|---|---|
| Queue ownership | `8c6d02` stores module at work B=`186ec58` +0; copies exactly c8 bytes from N to B+4; copies all five completion words to B+cc. This is a shallow copy: the pointed-to data is borrowed and must remain valid through completion. |
| Enqueue | At `8c6d5a`, `50ff1c` receives queue=`186ed38` and a new five-word record `[74ca7b,0,8c6d87,0,0]`. No invented Unix socket or external wire exists at this edge. |
| Enqueue failure | Source return zero enters `8c6d60..7c` and calls the saved completion with saved module. It clears occupancy but does not run work, flip the bank or satisfy observed-word equality. Nonzero enqueue follows the worker path. |
| Real consumer | `8c6d86` computes alternate bank=`203f4f8 + (selector XOR 1)*920`, selector is u8 at `1ad46a9`. It calls `351620(B+4, alternate_bank)` → `8c6e64` → **`8c736a`**. |
| Effects still missing | `8c6e64` clears the 23B diagnostic span from `877c38()+2`, increments the u16 from `877af8()`, and calls `8c736a(N, bank)`. Optional diagnostic/time work uses actual flag bytes at `1aa44a2+3f/+5a`. The per-command effects, resource inputs and output u16 at bank+0 inside `8c736a` have not been closed. This is the precise first missing backend business API. |
| Publish then completion | Only after the wrapper returns does `8c6db6..ca` XOR the selector. `8c6dbe..dc` invokes the saved record with saved module2. `637074` loads record+8 (`4de191`), calls `4de190(2)`; DMB SY then clears busy[2]. |
| Observe and transition | Later `4dab4a..62` normally reads `u16[(G+10)+0]`, calls `b1f1bc(2, value)`, storing M+36. The `8004`/`817f` boundary requires equality to the **current full requested word**. G+10 points to P+2950, a separate view from the published slot-2 bank G+40: the actual refresh/copy chain between them remains unclosed. Never substitute G+40 for G+10. |

Proposed finite backend API boundary (a design contract, **not an existing symbol**): `cp_slot2_enqueue(view200, borrowed_context, done_record20, module2)` → consume `cp_slot2_execute_8c736a(view, alternate_bank)` → actual selector publication → recorded cleanup callback → normal observed-word read. Reject missing/unknown pointer spans, prerequisites or effects and retain pending work. Snapshot/cancel paths must distinguish failed cleanup from completed bank publication. No `set_module_bit`, event-ready shortcut, or f000 send belongs in this first implementation.

This is useful parallel work because all copying, queue owner, callback target, failure branch, bank stride and publication order are pinned. It is **not yet a drop-in successful 0323 backend**: the command-specific `8c736a` contract and normal-view refresh must be finished first. There is no basis to route this to `full_adf_dispatch` or `adf-proc-device`.

## Other first-path consumers and reuse limits

Slot0 `011a` decodes table entry at CPVA `e798e0` through `4ba624`: exact12B **`0ac90300200000a000000000`** (u32 `0003c90a,a0000020,00000000`). It is copied to P+19b0; normal observed0 still comes from P+e18+ba4. This table copy is a concrete preparation sub-operation, not proof of full module0 completion. Existing cold control only consumes slot0 `0100`/`0108` in its finite 3007 profile and cannot admit this operation.

Slot1 `0202` is the earliest asynchronous operation on known 6→77, through `991e12(N, record20, module1)`. Entry copies c8 bytes to `165cad8`, record to+c8, module to+dc. It posts queue returned by `99424c` using `[993eed,0,39e499,0,0]`. Failure calls completion without publication. Worker `39e498` selects the alternate 210B bank at `10fe9c8 + (u8[1b15ff4] XOR1)*210`; in derived mode other than1/2, `9925b0` writes **`0202`** from `(*N)+8` to bank+14 (raw **`0202`**), and `39e5a6..ac` flips the selector. Prefix `a15eb6` and postwork `a15ee2`, `9aa584`, `9dc2d0`, `a96e28` remain mandatory original effects. Final callback at `39ed18..38` invokes record with module1. Normal completion reads G+44+14, distinct from requested+8. The existing `cp_slot1_enqueue` checks exactly `0201` at line70 and requires separate prefix/postwork callbacks; widening that check alone would omit input-dependent effects and is not a completed implementation.

Source review of `cp_cold_begin` confirms command3007-only admission and current0; `consume_known` only understands 0100/0108 for slot0. The graph connection entrypoints own endpoint/pin/format/queue state and do not receive these c8B CP module views, module completion records or sequencer storage. `adf-proc-device.c:521` matches external `u16[0]=200d,u16[2]=0323`; its event2/9058003f source is a different wire namespace. No module slot is marked consumed from any of those existing successes.

## External wire, remaining unknowns, and reproducibility

The real pending request is target=`90030001`, source=`80020002`, tid381, full24B **`00002c302700008000000000000000000000000000000000`**, correlation=`80000027`. The reused chain remains external302c → family0/event17 → internal3041/mode0 → family1/event32d → dedicated302c reply. Defined twelve-byte response pattern is **`01 ?? 2c 30 27 00 00 80 00 f0 00 00`**; byte1 is not defined by the source producer and must not be invented as zero. Do not use generic31c/301d. Module2 completion is its internal callback/observed word, not a synthesized copy of this external reply. Final reply ownership must eventually allocate an independent12B buffer, set source90030001, enqueue to the saved original sender, preserve the original correlation, release on failed send and verify original AP consumption/free; none is performed by this investigation.

Path P1 (`callflow`, E1/F1–F3): parent-established state/variant → real phase1 observer effects → actual selected module work → normal bank/view publication and completed callbacks → full-u16 boundary equality → central target/current transition → phase3 effects → dedicated reply with original owner. Items still open: actual state6/8; complete module0 and module8 business work; module2 `8c736a`/view refresh; other required modules' exact parameter/effect graphs; live observer state; full prefix/postwork effects; original CP request/reply admission and AP free evidence. No JPEG stage is reached by this report. Later AP/EE/JPEG work remains beyond this boundary.

Reproduce E1 offline from `runtime/analysis`: read `menu-root/cp/cpapp-b.bin`, verify its whole-file SHA above, then for each JSON pin read `blob[raw:raw+length]`, compare bytes and SHA; disassemble code pins with Capstone ARM Thumb/little endian at CPVA. The JSON also pins data tables, which must not be disassembled as instructions. For mask verification explicitly iterate slots0..12 and test `(mask & (1<<slot))`; compare full u16 source words, never infer module identities from a Python population-count result.

Timeline: reused prior eight-window transition evidence; identified independent family observer objects and u16 completion gate; pinned module1 queue; incorporated parent variant0 steering; pinned module2 queue/worker/callback and stopped at its first unclosed business callee. Validation for this deliverable is original SHA/byte-window/readback consistency only. No runtime test, production rebuild, or native module consumption is claimed.
