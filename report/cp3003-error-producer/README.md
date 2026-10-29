# CP3003 error-producer investigation

**Source error producer found: NO, within this bounded investigation.** The original CP router and START rejection paths inspected here do not authorize a CP3003 failure packet. The outer event-2 rejection callback actually invokes the existing **16-byte F000 completion**, including all four live data bytes. The synchronous START guard returns internal `-1/-2`; neither value is a wire status. No diagnostic profile or runtime change is delivered. `native_capture=false`; the parent-reported actual AP state remains 3003 / EE0, with no JPEG or MP4.

## Scope and reproduction

This is owner-authorized, offline, public ALLLANG firmware research. The only new delivery files are this README, [source-pins.json](source-pins.json), and research outputs under [the dedicated scratch directory](../../runtime/analysis/scratch/cp3003-error-producer/). Existing changes, frozen inputs, original binaries, private/full-system material, VM execution, hardware, network and physical SD are excluded. The AP assertion contract and the four-byte status algorithm are carried forward from the two requested reports, not re-investigated.

The source is `runtime/analysis/menu-root/cp/cpapp-b.bin`, 18,090,880 bytes, SHA-256 `f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428`. Mapping is `CPVA = raw + 0x108000`, only within `[0x108000,0x1248b80)`. This is raw ARM/Thumb code, with no ELF imports/exports. E-imports equivalent: original internal calls to allocator `565204`, sender `564b38`, source setter `bec024` and release `565300` are visible in the bounded transport window; no whole-image API survey is claimed.

From the `2026-10-17-qemu-native-camera` root:

```bash
python3 runtime/analysis/scratch/cp3003-error-producer/research.py --extract-only
python3 runtime/analysis/scratch/cp3003-error-producer/publish.py --check
```

The first command re-extracts ten final windows, totaling 7,812 bytes; adjacent handler/return/callback ranges were consolidated. The second verifies source identity, every full window hash and original bytes, and the important call/branch/field instructions. It does not run a VM or a full regression suite.

Native Kuna 1.892 was invoked on the original image with `--target ARM:LE:32:v7 --isa thumb --base 0x108000 --max-fn-seconds 8 --no-vars`; each corrected call also had an 8-second process timeout. All seven corrected calls returned timeout/124 with no usable decompilation. Initial calls returned 2 because raw-image mode rejects `--functions`; those commands and diagnostics were preserved separately. Claims below are checked against original bytes and Capstone Thumb instructions, not unsuccessful decompiler output. Commands, return codes, diagnostics and elapsed times are in scratch `kuna-runs*.json` and `*.stderr`. The source and cached branch-index identities are pinned in the JSON. No 1,000-constructor traversal was performed.

## Actual routing and rejected branches

| Evidence | Original source and guards | Finding |
|---|---|---|
| E1 router/decode | `4b3a7c` receives on `90030001`; `4b3b0a..16` accepts type 0 or 2, then `4b3b1a → 4b6064(request, origin)`. Decoder table at `4b608c`, command 3003 index 3, selects `4b6118`, event 2. `4b632c..42` sends handler0/event2/cookie/origin in a 32-byte envelope to `900302d9`. | F1: 3003 is an explicit START event, not an unsupported-command case. |
| E2 unsupported/router rejection | Decoder default `4b60fe..16` logs through `4b65ac`, sets local return 1 and returns at `4b6346`; receiver discards the decoder return and frees the original request at `4b3b3a`. Other unsupported message types skip decoder and reach cleanup. | F2: these inspected rejection branches contain no reply construction. Relabeling a valid 3003 as unsupported would change the original dispatch predicate. |
| E3 outer rejection | `b20220` compares event2 at `b20286/88`, then `b20332..3a` returns exactly `(u32[handler+28] == 1)`. The existing outer-dispatch contract selects rejection vtable slot +1c when this predicate is 1. `4b4b00` selects event2 at `4b4b3c/3e`; `4b4b92` loads original cookie and origin and `4b4b98 → b224ae`. | F3: the outer rejection callback uses the same F000/data collector, not an error producer. |
| E4 perform/precheck | In the original `ExecModeHandler::perform` (`e77b10` contains Thumb pointer `4b4061`, carried from the prior source-pin record), event2 sets CamMain+28=2 via `4b4092 → b21f04`. `4b4240 → b21fb4 → b1ef76(3003)`. Exactly 1 invokes `b224a8`; otherwise `4b4780 → b21898 → b21702(3003,0)`. | F4: a precheck shortcut produces ordinary completion; its alternative reaches START guard. CamMain+28 and handler+28 are different objects. |
| E5 guard return | `b2170e → 4b6958`; `b21712` returns immediately on nonzero. Guard 0 calls `4b28d8(3003,1)`, saves its returned sequence in shared root+1c and its mode in root+40, then explicitly returns 0 at `b21730`. | F5: synchronous guard errors propagate internally; START-machine return 0 is not converted to a protocol error here. |
| E6 failure tail | Slow event2 stores the guard return in r6 at `4b4784`. `4b48f2` tests r6+2. For -2, the code copies the 28-byte event, changes the copy's event to 13h and its origin field to 0, invokes handler vtable+20 twice (copy, then original), and sets handler+2c=2. Other returns call `b20396`; nonzero r6 then updates execution bookkeeping with `4b5874(...,1,event)`. | F6: -2 is a retry/ordering control branch; no error packet is made in this inspected tail. The virtual +20 enqueue target is not resolved here. |
| E7 state refresh | `b20396..b203c6` calls `4b4be8`, writes its result to handler+28, optionally calls `b221c6` on a 1→non-1 change, then mirrors that state at shared root+d54. | F7: this function is state refresh, not the reply selector its location might suggest. `4b4be8` is the first uninspected producer of the outer event2 predicate. |
| E8 transport/builders | `b224ae` and `4b6a70` show the F000/data collector and transport; `4b6b2c` independently builds a 12-byte type1/cmd/echo/status reply only when its object's saved destination is nonzero. No inspected 3003 failure branch reaches this generic 12-byte builder. | F8: availability of a generic status-taking API does not authorize a 3003 error reply. |

The inherited outer-dispatch slot selection is from [the 302c no-transition contract](../cp302c-no-transition-contract.md) and its exact byte pin at `b20010`; this report freshly checks the **event2-specific predicate and callback**, not the AP or 302c behavior. Original source pointer `e77b10=4b4061` and its full pin hash are carried in the JSON with provenance; no new vtable-wide scan is claimed.

## Synchronous START guard: predicates are not status codes

For command C=3003 and CamMain object S, `4b6958` performs:

1. If `b1ef76(C) != 0`, return 0.
2. If `b1f140(C) == 0` and `b1f2f8()` equals 7dh or 77h, log `Invalid request ... in PREPARE state` and return -1.
3. Otherwise, if `b1f140(C) != 0` or `b1f2c8() != 0`, retain return 0; if neither holds, log through `4b65ac` and retain -1. Commands 3037/3038 have a separate logging exception; 3003 does not.
4. Only when `b1f140(C) == 0` and `b1f2c8() == 1`, test `S+28 != 0` and `b1f174(u32[S+28],C) != 0`: both true replace the result with -2; otherwise log and return -1.

These are literal helper results and original comparisons. This task does not promote their mutable input history to known virtual values. **First missing guard function: `b1ef76(3003)` at `4b6968`, also used by the precheck.** The subsequent command-admission and transfer predicates are named at exact call sites in the source pins, but not reimplemented. No path writes -1 or -2 into a reply status field.

`4b28d8` additionally rejects an already-busy sequence (`u8[1b1df9a]==1` at `4b28ec`) through diagnostics and returns the existing sequence, and it returns/records sequence 0 if `b1f418` cannot select a transition (`4b2976 → 4b298c..98`). `b21702` does not branch on that returned sequence before returning 0. The diagnostic constants passed to `b4361c` on the busy branch are not evidence of an AP-directed CP3003 packet; the destination/wire producer is not present in this window.

## The only closed event2 rejection packet is still success

The outer callback `4b4b92` passes `r1=original_cookie`, `r2=original_origin`, `r0=handler+10` to `b224ae`. The ordinary `b224a8` entry instead loads r2 from its object's saved destination. Both reach the same builder:

| Field | Original source |
|---|---|
| Wire length | 16 bytes (`b224fe`, passed to `4b6a70`) |
| Type / command | byte +0=1; LE16 +2=3003 |
| Byte +1 | Not initialized by this builder; no claim it is source-known zero |
| Echo | LE32 +4=original request+4 |
| Status | LE32 +8=F000, fixed at `b224c4/ca` |
| Body | Four actual getter/cache bytes at +c..+f; not a failure parameter |
| Source | `90030001`, set through `bec024` at `4b6ac0` |
| Destination | Incoming original origin on outer rejection, passed through r2→r4→r3 to `4b6a70`; normal entry uses its saved destination |
| Ownership | Independent allocation at `4b6aa0`; send `4b6ad2`; failed send frees reply at `4b6ade` |

This closes the rejection **success** packet's source route; it supplies no error packet and does not remove any of the four data dependencies. It cannot serve as an unready-device fallback.

## Decision and implementation bounds

P1 (`path_type=callflow`): router → event2 → outer predicate → callback `4b4b92` → `b224ae` → `4b6a70` → original origin. E1/E3/E8 establish F1/F3/F8: this branch is fixed success with data, not a permitted error path.

P2 (`path_type=callflow`): perform event2 → precheck → `b21898` → guard → internal -1/-2 → bookkeeping/reordering/state refresh. E4/E5/E6/E7 establish F4/F5/F6/F7: no CP3003 error reply is closed in the bounded path. The first uninspected guard predicate is **`b1ef76`**; the first uninspected producer of outer handler state is **`4b4be8`**; the -2 path's **handler vtable+20 target** remains unresolved. Later asynchronous/error callbacks are not covered by a whole-image negative proof.

The minimal permitted implementation change is **none**. Keep missing START data blocked; do not translate host `-ENODATA`, internal -1/-2, a negative 32-bit code, or hardware-unready observations into a CP3003 status. Do not invoke the generic 12-byte builder without a positive 3003 source call and its actual predicate. Do not invoke F000 completion without the existing four-data contract. Closing the missing functions and their real virtual state/input history would be a separate bounded investigation, not authorization to force a gate.

Timeline: verified requested prior contracts and full image identity → used cached direct-branch candidates → extracted bounded router/START/return paths → preserved Kuna rejection/timeouts → checked the original outer event2 callback → pinned and verified report artifacts. This is ordinary firmware reverse analysis (`flavor=null`); all findings have `severity=n/a_re`, confidence high for the quoted original instructions, limited for absence outside these windows. No AP/UI/capture acceptance test was run, and no image-production claim is made.
