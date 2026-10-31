# SPDX-License-Identifier: MIT
"""Unexecuted late-site host mock drafts; parent integrates before one test pass.

Requires production late-sites.inc integration and the one registration-mock
branch documented in test-late-sites.c. Reuses the existing reviewed API header
and mock; this module never opens Sony code, a run, an image, or a guest device.
"""
import json
import importlib.util
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import pytest

_spec = importlib.util.spec_from_file_location('v3_late_observer_fixture_flags', Path(__file__).with_name('test_scope_observer.py'))
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
FLAGS, HERE, QEMU = _fixture.FLAGS, _fixture.HERE, _fixture.QEMU

SCRATCH = HERE.parents[1] / "runtime/analysis/scratch/functional-M-writer-v3-late-tests"
SITES = ("M_cmp_pre", "M_bne_pre", "request0_bl_pre")
OFFSETS = dict(zip(SITES, (0x209EE58, 0x209EE5C, 0x209EE9C)))
BASE = 0x5500000000
REGISTERS = ("pc", "x0", "x19", "x23", "x30", "cpsr", "sp",
             "TTBR0_EL1", "TPIDR_EL0", "x1")


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def late_binary(request):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix="late-" + request.param + "-", dir=SCRATCH))
    sanitize = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
                if request.param == "asan-ubsan" else [])
    binary = directory / "late-sites-mock"
    command = shlex.split(os.environ.get("CC", "cc")) + FLAGS + sanitize + [
        "-I", str(_fixture.BASE / "mock"), "-I", str(QEMU / "include/plugins"),
        str(HERE / "test-late-sites.c"), "-o", str(binary)]
    (directory / "compile-command.json").write_text(json.dumps(command, indent=2) + "\n")
    process = subprocess.run(command, capture_output=True, timeout=90)
    (directory / "compile.stdout.bin").write_bytes(process.stdout)
    (directory / "compile.stderr.log").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    return binary


def run_late(binary, scenario, io_failure=False):
    directory = Path(tempfile.mkdtemp(prefix=scenario + "-", dir=binary.parent))
    log = directory / "late.host.log"
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    process = subprocess.run([str(binary), scenario, str(log)], capture_output=True,
                             env=environment, timeout=30)
    (directory / "stdout.bin").write_bytes(process.stdout)
    (directory / "stderr.log").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b""
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    raw = log.read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.splitlines(keepends=True)
    assert len(lines) <= 179 and all(len(line) < 2048 for line in lines)
    rows = []
    for line in lines:
        fields = line.decode("ascii").split()
        row = dict(field.split("=", 1) for field in fields)
        assert len(row) == len(fields)
        assert row["status"] == "native_unverified" and row["identity"] == "unknown"
        assert row["binding"] == "unbound" and row["pid"] == row["tid"] == "unknown"
        assert row["capture"] == row["physical"] == "0x0"
        rows.append(row)
    assert rows[0]["kind"] == "begin" and rows[0]["schema"] == "readonly_scope_v3"
    assert rows[0]["producer_sites"] == "0x3" and rows[0]["producer_quota"] == "0x10"
    assert rows[0]["producer_anchor_length"] == "0x18"
    assert not any(row["kind"] == "M_producer" for row in rows)
    selected = [row for row in rows if row["kind"] == "late"]
    if io_failure:
        assert b"scope_observer_host_error stage=" in process.stderr
        assert len(process.stderr.splitlines()) == 1
        assert not any(row["kind"] == "end" for row in rows)
    else:
        assert process.stderr == b""
        assert rows[-1]["kind"] == "end" and rows[-1]["close_result"] == "unknown"
        assert sum(row["kind"] == "end" for row in rows) == 1
        assert rows[-1]["producer_anchor_found"] == "0x0"
        assert rows[-1]["producer0_records"] == rows[-1]["producer1_records"] == "0x0"
        assert rows[-1]["producer_sequence"] == "0x0"
        assert rows[-1]["producer2_anchor_found"] == rows[-1]["producer2_records"] == "0x0"
        assert int(rows[-1]["producer2_base"], 16) == int(rows[-1]["producer2_conflicting_base"], 16) == 0
        assert [int(row["late_sequence"], 16) for row in selected] == list(range(1, len(selected) + 1))
        assert int(rows[-1]["late_sequence"], 16) == len(selected)
        for site, counter in zip(SITES, ("late0_records", "late1_records", "late2_records")):
            group = [row for row in selected if row["site"] == site]
            assert [int(row["ordinal"], 16) for row in group] == list(range(1, len(group) + 1))
            assert int(rows[-1][counter], 16) == len(group) <= 16
    return rows, selected


def check_context(row, optional=True, mode="EL0t"):
    assert row["vcpu"] == "0x0" and row["callback_phase"] == "before_instruction"
    assert int(row["candidate_base"], 16) == BASE
    assert int(row["event_pc"], 16) == BASE + OFFSETS[row["site"]]
    assert int(row["gdb_pc_raw"], 16) == BASE + 0x2E068CC
    assert row["gdb_pc_raw"] != row["event_pc"]
    assert row["anchor_length"] == "0xc"
    assert row["x19"] == "0x0123456789abcdef"
    assert row["x23"] == "0xf123456789abcdef"
    assert row["x30"] == "0xabcd005500abcdef"
    assert int(row["x30"], 16) != BASE + 0x209EEA0
    cpsr = int(row["cpsr_raw"], 16)
    assert int(row["nzcv"], 16) == cpsr & 0xF0000000
    assert row["nzcv_mask"] == "0xf0000000" and int(row["cpsr_m"], 16) == cpsr & 0x1F
    assert row["context_mode"] == mode and row["api_ok"] == "0x1"
    for reg in ("gdb_pc", "x0", "x19", "x23", "x30", "cpsr"):
        assert row[reg + "_read_length"] == ("0x4" if reg == "cpsr" else "0x8")
        assert row[reg + "_api_ok"] == "0x1"
    for name, raw in (("sp", "0x0000007ffffffd00"),
                      ("ttbr0_el1", "0x1234005500456000"),
                      ("tpidr_el0", "0xfedcba9876543210")):
        assert row[name + "_available"] == ("0x1" if optional else "0x0")
        assert row[name + "_raw"] == (raw if optional else "unknown")
        assert row[name + "_read_length"] == ("0x8" if optional else "0x0")
        assert row[name + "_api_ok"] == ("0x1" if optional else "unknown")
    if row["site"] in SITES[:2]:
        assert int(row["loaded_M_u32"], 16) == int(row["x0"], 16) & 0xFFFFFFFF
        assert "x1" not in row and "w1" not in row and "x1_read_length" not in row
        if row["site"] == "M_cmp_pre":
            assert row["flags_phase"] == "before_cmp" and "source_next_pc" not in row
        else:
            z = (cpsr >> 30) & 1
            assert row["flags_phase"] == "after_cmp_before_bne" and int(row["z"], 16) == z
            assert int(row["source_next_pc"], 16) == BASE + (0x209EE60 if z else 0x209EE80)
            assert row["source_next_basis"] == "cpsr_Z"
    else:
        assert row["lr_phase"] == "before_bl" and "loaded_M_u32" not in row
        assert int(row["w1"], 16) == int(row["x1"], 16) & 0xFFFFFFFF
        assert row["x1_read_length"] == "0x8" and row["x1_api_ok"] == "0x1"


@pytest.mark.parametrize("scenario", ("late_exact", "late_optional_absent", "late_kernel"))
def test_exact_triplets_widths_lazy_pc_and_optional_raw_context(late_binary, scenario):
    rows, selected = run_late(late_binary, scenario)
    assert [row["site"] for row in selected] == list(SITES)
    for row in selected:
        check_context(row, optional=scenario != "late_optional_absent",
                      mode="other_aarch64" if scenario == "late_kernel" else "EL0t")
    assert selected[0]["x0"] == "0x00000000fedcba98"
    assert selected[0]["loaded_M_u32"] == "0xfedcba98"
    assert selected[0]["nzcv"] == "0xa0000000"
    assert selected[1]["z"] == "0x1" and selected[1]["nzcv"] == "0x60000000"
    assert selected[2]["x1"] == "0x0000000000000000" and selected[2]["w1"] == "0x00000000"
    assert rows[-1]["stop"] == "none" and not any(row["kind"] == "fault" for row in rows)


def test_raw_values_flags_and_current_lr_are_not_normalized(late_binary):
    rows, selected = run_late(late_binary, "late_raw")
    for row in selected:
        check_context(row)
    assert selected[0]["x0"] == "0xfeedface80000001"
    assert selected[0]["loaded_M_u32"] == "0x80000001" and selected[0]["nzcv"] == "0x60000000"
    assert selected[1]["loaded_M_u32"] == "0x00000001" and selected[1]["z"] == "0x0"
    assert selected[2]["loaded_M_u32"] == "0x80000001" and selected[2]["z"] == "0x1"
    assert selected[3]["x0"] == selected[4]["x0"] == "0x123456789abcdef0"
    assert selected[3]["x0"] != selected[3]["x19"]
    assert selected[3]["x1"] == "0xdeadbeef00000000" and selected[3]["w1"] == "0x00000000"
    assert selected[4]["x1"] == "0x11223344cafebabe" and selected[4]["w1"] == "0xcafebabe"
    assert rows[-1]["fault_lines"] == "0x0"


def test_every_byte_shape_short_tb_cross_tb_and_low12_collision_are_silent(late_binary):
    rows, selected = run_late(late_binary, "late_reject")
    assert not selected and not any(row["kind"] == "fault" for row in rows)
    assert rows[-1]["stop"] == "none" and rows[-1]["candidate_found"] == "0x1"


def test_translation_before_discovery_and_retranslation_keep_userdata_and_quotas(late_binary):
    rows, selected = run_late(late_binary, "late_order_and_userdata")
    assert [row["site"] for row in selected] == list(SITES)
    for row in selected:
        check_context(row)
    assert rows[-1]["fault_lines"] == "0x0" and rows[-1]["ambiguous"] == "0x0"
    assert sum(row["kind"] == "candidate" for row in rows) == 1


def test_success_quotas_fault_budget_and_original_callback_quotas_are_independent(late_binary):
    rows, selected = run_late(late_binary, "late_limits")
    assert len(rows) == 131 and len(selected) == 48
    assert [row["site"] for row in selected] == [SITES[0]] * 16 + [SITES[2]] * 16 + [SITES[1]] * 16
    for row in selected:
        check_context(row)
    end = rows[-1]
    assert end["late_sequence"] == "0x30" and end["fault_lines"] == "0x20"
    assert int(end["suppressed_faults"], 16) == 48
    assert end["lr0_records"] == end["lr1_records"] == end["poweron_records"] == "0x10"
    assert sum(row["kind"] == "entry" for row in rows) == 32
    assert sum(row["kind"] == "poweron_context" for row in rows) == 16


def test_missing_x1_fails_bl_only_and_preserves_original_scope(late_binary):
    rows, selected = run_late(late_binary, "late_x1_absent")
    assert [row["site"] for row in selected] == list(SITES[:2])
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "unknown_register" and fault["reg"] == "x1"
    assert fault["required_length"] == "0x8" and fault["read_attempted"] == "0x0"
    assert fault["read_length"] == fault["api_ok"] == "0x0"
    assert rows[-1]["lr0_records"] == rows[-1]["lr1_records"] == "0x1"
    assert rows[-1]["stop"] == "none"


@pytest.mark.parametrize("scenario,reg,length,ok", [
    *(("late_short_" + reg, reg, 3 if reg == "cpsr" else 7, 1) for reg in REGISTERS),
    *(("late_api_" + reg, reg, 4 if reg == "cpsr" else 8, 0) for reg in REGISTERS),
    ("late_long_cpsr", "cpsr", 8, 1), ("late_long_x1", "x1", 9, 1),
])
def test_each_failed_or_wrong_width_read_rejects_whole_record_then_recovers(
        late_binary, scenario, reg, length, ok):
    rows, selected = run_late(late_binary, scenario)
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "register_read" and fault["reg"] == reg
    assert int(fault["required_length"], 16) == (4 if reg == "cpsr" else 8)
    assert int(fault["read_length"], 16) == length and int(fault["api_ok"], 16) == ok
    row, = selected
    check_context(row)
    assert row["site"] == (SITES[2] if reg == "x1" else SITES[0])
    assert row["ordinal"] == row["late_sequence"] == "0x1" and rows.index(fault) < rows.index(row)


def test_aarch32_is_rejected_and_raw_aarch64_can_resume(late_binary):
    rows, selected = run_late(late_binary, "late_aarch32")
    faults = [row for row in rows if row["kind"] == "fault"]
    assert [row["site"] for row in faults] == list(SITES)
    assert all(row["reason"] == "not_aarch64" and row["cpsr_raw"] == "0xa00003d0"
               and row["cpsr_m"] == "0x10" for row in faults)
    assert len(selected) == 3
    for row in selected:
        check_context(row)


@pytest.mark.parametrize("scenario,reason", (("late_vcpu", "vcpu_limit"),
                                           ("late_invalid_metadata", "invalid_callback_context")))
def test_vcpu_and_opaque_metadata_are_fail_closed(late_binary, scenario, reason):
    rows, selected = run_late(late_binary, scenario)
    assert not selected
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == reason and fault["site"] == "late"
    assert rows[-1]["stop"] == reason


@pytest.mark.parametrize("scenario", ("late_write_failure", "late_flush_failure"))
def test_partial_or_failed_host_record_never_spends_success_counters(late_binary, scenario):
    run_late(late_binary, scenario, io_failure=True)
