# A7C II input coverage

This batch adds source-backed hold/release behavior to the existing GTK camera window and existing serial owner. The original menu/UI layout, raw control registry and App32/Infra20 encoders remain authoritative. Keyboard, mouse/touch and controller callers now share contact ownership, ordered shutter contacts and bounded dial requests. Offline checks execute the real `inject-key.c` against mocked OSAL queues and execute the production queue/serial-owner callers.

This is host input implementation and offline verification. No VM, live display, QMP, network, physical SD, private settings, full-system image or original firmware asset is opened by this suite. Firmware consumption, AF/AE, parameter effects, photographs and movies remain part of the main session's unified VM acceptance. A dedicated AEL contact and independent exposure-compensation contact are unsupported; their values are not inferred.

## Run the offline checks

From the `2026-10-17-qemu-native-camera` directory, with the project's existing Python/pytest and host C compiler:

```sh
python3 -m pytest report/camera-input-coverage/test_input_bindings.py \
  runtime/analysis/test_live_transport_retention.py \
  runtime/analysis/test_menu_control.py \
  runtime/analysis/test_key_injection.py \
  runtime/analysis/test_app_input.py -q
```

The new suite contains 164 cases; together with the listed existing regressions the result is **198 passed, 5 subtests passed**. GTK caller checks use the production class/button closures with in-memory widget/event fixtures. They verify callback routing and lifecycle, not GTK rendering or a real display server.

## Controls and host bindings

Raw values come from `menu_live.KEY_DEFINITIONS`, `key_definition`, `key_status_command` and `key_command`; there is no second firmware mapping table in executable code. `source-pins.json` records the prior original 2.01 evidence, route layouts, expected registry values and the exact source hashes used by these checks.

| Physical control / shared label | Keyboard | Implemented input |
| --- | --- | --- |
| MENU | M / Escape | Hold/release raw contact |
| C1 | F1 | Hold/release raw contact |
| C2 / delete | F2 / Delete | One shared physical contact across both names |
| Shutter half / full | H / S | Half contact; full acquires half before full and releases full before half |
| REC | R | Hold/release REC contact; recording completion is separate |
| AF-ON | A | Hold/release AF-ON contact; autofocus completion is separate |
| Fn | F | Hold/release Fn contact |
| Center | Enter | Existing ENTER contact |
| D-pad / DISP / ISO shared labels | Arrow keys | Existing four contacts, aliases share ownership |
| Control wheel | Comma / period | Signed relative ticks; existing wheel surface also supports scroll and drag |
| Front dial | Q / E | Signed relative ticks; existing mouse buttons/scroll surfaces |
| Rear dial | `[` / `]`, PageUp / PageDown | Signed relative ticks; existing mouse buttons/scroll surfaces |
| Still/movie/S&Q selector | 1 / 2 / 3 | Existing status 1 / 2 / 3, no release message |
| Mode dial | F5 through F12 | AUTO / P / A / S / M / MR1 / MR2 / MR3; original eight wire positions |
| Independent exposure-compensation contact | None | Unsupported; not substituted with DOWN or the rear dial |
| Dedicated AEL contact | None | Not established as a dedicated control on this model; custom button function does not establish a raw contact |

Mode's existing popover and all original buttons remain in place. Space and Tab retain GTK focus behavior. Controller integrations call `InputBindings.press(name, source)`, `release(source)`, `activate(...)` or `post('rotate', dial=..., ticks=...)` using a stable distinct source per trigger; no new device-scanning dependency is introduced.

## Production call path and exact changed paths

The new files are `report/camera-input-coverage/input_bindings.py`, `test_input_bindings.py`, `README.md` and `source-pins.json`.

Four existing runtime files have minimal integration edits:

| File under `runtime/analysis/` | Integration |
| --- | --- |
| `camera_ui.py` | Production `CameraUI.__init__` installs `attach_gtk` when its VM supports the lifecycle. Existing button, keyboard, touch, scroll and ring surfaces route through bindings. OFF/close request cleanup; backend errors remain visible. |
| `menu_control.py` | `VM.enqueue` validates `camera_input` commands and retains the original bounded queue. Actual replies publish authoritative `input_state`; release/cleanup remain admissible during SD transitions/faulted state. |
| `menu_live.py` | Loads this delivered module and constructs `InputSession(live_serial, app_input=...)` inside `run_live`. Every input executes on the existing serial owner. Cleanup must succeed before SD export; legacy tap routes are retained and rejected while lifecycle contacts are held. |
| `qemu-menu-probe.py` | Includes the delivered `input_bindings.py` in the existing runtime source receipt. Its existing `run_live` invocation remains the serial-owner entry point. |

Call flow: existing GTK/controller caller → `InputBindings` → `VM.enqueue` → existing control channel → `menu_live.run_live` → `InputSession` → original `key_status_command` / `key_command` → existing `serial_command` → original `inject-key.c` → original OSAL queue. No app-holder writes or UI-label simulation is used.

`InputSession` requires an explicit App32/Infra20 selection. App32 uses queue/source `0x5503e0`, 32 bytes and `from_type=0`; Infra20 uses queue `0x807a0020`, source `0x92840747`, 20 bytes and `from_type=1`. The legacy single-slot file mailbox cannot support held contacts and does not advertise lifecycle support.

## Lifecycle and errors

Local physical source bookkeeping and serial-owner held state are distinct. Queue acceptance changes only local source bookkeeping. A release removes authoritative held state only after the existing serial command succeeds. A failed/ambiguous contact send records its raw code as uncertain and blocks new input until release/cleanup succeeds. Errors and any held contacts remain visible after a failed cleanup; SD export refuses to proceed with unresolved contacts.

Repeated presses from the same source do not duplicate raw press events. Distinct sources and C2/delete aliases share a physical contact until its final owner releases. Touch identity uses the actual device/sequence tuple, with a distinct generated source token; hash collisions do not merge fingers. Mouse capture, focus loss and broken grabs request cleanup. Full-shutter cleanup precedes half-shutter cleanup even when they have separate owners.

Dial left/right are the original single status values `0xfffffc00` / `0x400`, with no artificial zero release. Each request is bounded to 1–32 ticks. Fractional smooth scroll is accumulated independently per dial; oversized bursts are clamped and their excess is discarded. Ring motion uses signed angular wrapping across ±π and ignores another source's drag. A partially failed rotation reports the completed prefix and is not replayed automatically because a failed send may be ambiguous.

## Evidence → finding → path

Flavor: ordinary implementation report (`null`). Scope is this offline input batch and the repository's existing [QEMU working rules](../../../../AGENTS.md); hardware access and VM acceptance are excluded.

| Evidence | Observation / reproduction |
| --- | --- |
| E-001 | Prior source evidence is preserved in [remaining-body-controls.md](../remaining-body-controls.md) and `runtime/analysis/test_app_key_remap.py`: firmware SHA-256 `2ea02f7ecbc5bb917316fe8ef4ce5ffd87eb66efaae78ba2ce11420552df539b`, raw/canonical tables at VA `0x3704b98` / `0x3706e98`, explicit mode/selector enum evidence. These original assets are not reopened by this suite. Reproduction of that prior binary evidence requires the optional original asset. |
| E-002 | [source-pins.json](source-pins.json) pins house constants/encoders and implemented runtime callers by SHA-256. The offline suite checks drift against those sources and checks every supported mapping, alias, mode position and both routes. Reproduce with the command above. |
| E-003 | [test_input_bindings.py](test_input_bindings.py) compiles the actual `inject-key.c`, mocks `osal_valloc_msg_wait` / `osal_set_msg_src` / `osal_snd_msg` / `osal_free_msg`, and checks exact queue/source, byte length, every word and release order. Failed sends also check cleanup and free behavior through the existing injector. Reproduce with the command above. |
| E-004 | The same suite invokes actual `run_live`, `VM.enqueue`, extracted actual VM response/GTK installation branches and the existing GTK button closures with transport/widget fixtures. It checks installation, dispatch, queue rejection, focus/broken-grab cleanup and export refusal after failed release. Reproduce with the command above. |

F-001 (validated for offline implementation; E-002/E-003/E-004): all currently source-closed controls have a shared callable lifecycle and an active production caller path. Confidence is high for tested host/encoding behavior. Residual risk is real GTK/VM scheduling and original-firmware consumption, which require unified acceptance.

F-002 (bounded unsupported conclusion; E-001/E-002): this batch has no source-backed independent exposure-compensation or dedicated AEL contact. Those names cannot be promoted to raw controls by assuming a custom assignment or generic direction.

P-001 (callflow; E-002/E-003/E-004): an original GTK button/key/controller source creates a validated request, the VM serializes it, the existing live owner acquires/releases shared contacts in order, the original encoder sends exact OSAL messages, and only completed serial sends update authoritative state. Failure retains state and blocks export until cleanup succeeds. This path ends at input submission; AF/AE, image/codec output and files are separate acceptance evidence.

No per-button VM, screenshot run, new dependency, physical device operation or additional delegate was used. Main-session unified self-test and VM acceptance remain required.
