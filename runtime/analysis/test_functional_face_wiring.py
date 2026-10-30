# SPDX-License-Identifier: MIT
"""HOSTTEST actual main face hooks + real facade/DMM/registry; no original AP boot proof."""
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess

import pytest

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("face_graph_fixture", HERE / "test_final_graph_observer_wiring.py")
assert _spec is not None and _spec.loader is not None
_graph_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_graph_fixture)
function = _graph_fixture.function
MODES = (
    "units", "queued", "reentry", "caller-goldens", "dispatch", "canonical", "saved-identity",
    "disabled", "strict", "non-cp", "null", "size39", "size41", "other-unit", "op2a",
    "speech0", "speech1", "share-speech", "no-size", "no-source",
    "bad-library-base", "bad-appfw-base", "bad-suffix", "bad-prefix", "bad-va", "null-caller",
    "dladdr-failed", "null-library", "null-base", "no-dladdr", "first-bl", "second-bl",
    "short-first", "short-second", "read-error", "open-failed", "source0", "source-cp", "source-max",
    "source-domain", "control-uninit", "control-not-started", "control-fault", "setup-error",
    "receive-failure", "receive-gates", "no-free-observe", "ticket-retained", "wrong-queue",
    "wrong-tid", "old-ticket", "failed-free", "request-free-failure", "send-failure",
    "fork", "pointer", "no-snapshot-epoch", "ambiguous-close",
    "ap-observer", "ap-observer-send-failure", "ap-observer-untrusted",
)


def extracted_source():
    source = (HERE / "menu-observe.c").read_text()
    # Keep these helpers byte-for-byte, including the uint64_t owner helper.
    helpers = source[source.index("static uint64_t functional_face_producer_owner(void) {"):
                     source.index("static int functional_vdf_prepare(void) {")]
    declarations = "\n".join(line for line in source.splitlines()
                             if line.startswith("static ") and any(
                                 name in line for name in (" functional_face_used;", " functional_face_owner_pid;",
                                                          " functional_face_ticket;", " functional_face_ap_state;")))
    assert declarations.count(";") == 4
    all_sent = function(source, "osal_snd_msg")
    ap_sent = all_sent[all_sent.index("    int result,ap_traced=0;"):all_sent.index("    if (observed) {", all_sent.index("    int result,ap_traced=0;"))]
    ap_sent = ap_sent.replace("__builtin_return_address(0)", "fixture_caller")
    all_freed = function(source, "osal_free_msg")
    ap_freed = all_freed[all_freed.index("    int result=real_free_msg(id,message),saved_errno="):
                        all_freed.index("    if(functional_camera_enabled)(void)functional_jpeg_codec_observe_freed")]
    sent = all_sent
    sent = sent[sent.index("    if (id == 0x9061003c && message && real_msg_size"):
                sent.index("    if (capid_enabled &&")]
    sent = sent.replace("__builtin_return_address(0)", "fixture_caller")
    sent = sent.replace("__builtin_frame_address(0)", "(void *)0")
    freed = function(source, "osal_free_msg")
    # Actual first dispatch, then the original-free fallback for unrelated messages.
    freed = freed[:freed.index("    if(native_background_start_release(")]
    freed += "    (void)media_mount_trace;fallback_frees++;return real_free_msg(id,message);\n}\n"
    return {"/* ACTUAL_FACE_DECLARATIONS */": declarations,
            "/* ACTUAL_AP_RECORD */": function(source, "functional_face_ap_record_event"),
            "/* ACTUAL_AP_SEND */": ap_sent,
            "/* ACTUAL_AP_FREE */": ap_freed,
            "/* ACTUAL_FACE_HELPERS */": helpers,
            "/* ACTUAL_CP_RECEIVE */": "\n".join(function(source, name) for name in
                                               ("native_cp_state_received", "u_osal_rcv_msg_tmo")),
            "/* ACTUAL_FACE_FREE */": freed,
            "/* ACTUAL_DMM_DISPATCH */": sent}


@pytest.fixture(scope="module", params=[False, True], ids=["c11", "asan-ubsan"])
def face_wiring_binary(tmp_path_factory, request):
    root = tmp_path_factory.mktemp("actual-face-wiring")
    code = (HERE / "test-functional-face-wiring.c").read_text()
    for marker, snippet in extracted_source().items():
        assert code.count(marker) == 1
        code = code.replace(marker, snippet)
    generated = root / "actual.c"
    generated.write_text(code)
    binary = root / "actual"
    flags = ["-std=c11", "-O1", "-g", "-Wall", "-Wextra", "-Werror", "-pedantic", "-pthread"]
    if request.param:
        flags += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
    command = [*shlex.split(os.environ.get("CC", "cc")), *flags, "-I", str(HERE), str(generated),
               *(str(HERE / name) for name in ("functional-face-runtime.c", "functional-face-registry.c",
                                               "functional-face-dmm.c", "functional-face-ap-observer.c", "dmm-service.c")), "-o", str(binary)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    return binary


@pytest.mark.parametrize("mode", MODES)
def test_actual_face_main_wiring(face_wiring_binary, mode):
    options = "detect_leaks=1:halt_on_error=1"
    if mode == "pointer":
        options += ":quarantine_size_mb=0:thread_local_quarantine_size_kb=0"
    result = subprocess.run([str(face_wiring_binary), mode], capture_output=True, text=True, timeout=20,
                            env=dict(os.environ, ASAN_OPTIONS=options,
                                     UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1"))
    assert result.returncode == 0, result.stdout + result.stderr
    assert f"FACE_WIRING_HOSTTEST_PASS mode={mode}" in result.stdout
    if mode == "units":
        assert "COUNTS units=3 write=514304 read=514304 request_free=24 reply_free=24 ledger_commit=18 speech_unchanged=1" in result.stdout
    if mode == "caller-goldens":
        assert "CALLER anchors=5 actual_pread=10 physical_verified=0 original_cp_verified=0" in result.stdout
    if mode == "canonical":
        assert "CANONICAL rejected_mutations=150 transport_callbacks=0" in result.stdout
    if mode == "pointer":
        assert "POINTER real_malloc_reuse=1 fallback_free_once=1" in result.stdout
