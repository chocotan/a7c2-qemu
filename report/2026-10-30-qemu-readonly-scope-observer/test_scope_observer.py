# SPDX-License-Identifier: MIT
"""Unexecuted host mock drafts; no QEMU process, guest code, memory, or images.

The C harness includes the production plugin and the reviewed real API header.
Only GLib's small used surface and QEMU's public entry points are mocked.
All compiler output, executables, and scenario logs stay in the approved scratch.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import tempfile

import pytest

HERE = Path(__file__).resolve().parent
QEMU = HERE.parents[1] / "source/build/qemu-SRBXNK/qemu-11.1.2"
SCRATCH = HERE.parents[1] / "runtime/analysis/scratch/functional-M-v2-plugin-tests"
FLAGS = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-pedantic", "-O1", "-g"]
REGISTERS = ("pc", "x0", "x19", "x20", "x21", "x23", "x24", "x29", "x30", "cpsr", "sp")
TOKENS = ("TTBR0_EL1", "TPIDR_EL0")
POWERON_REGISTERS = ("pc", "x0", "x2", "x30", "cpsr")


@pytest.fixture(scope="module", params=("strict", "asan-ubsan"))
def observer_binary(request):
    SCRATCH.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=request.param + "-", dir=SCRATCH))
    sanitize = (["-fsanitize=address,undefined", "-fno-sanitize-recover=all",
                 "-fno-omit-frame-pointer", "-fno-pie", "-no-pie"]
                if request.param == "asan-ubsan" else [])
    binary = directory / "scope-observer-mock"
    command = shlex.split(os.environ.get("CC", "cc")) + FLAGS + sanitize + [
        "-I", str(HERE / "mock"), "-I", str(QEMU / "include/plugins"),
        str(HERE / "test-scope-observer.c"), "-o", str(binary)]
    (directory / "compile-command.json").write_text(json.dumps(command, indent=2) + "\n")
    process = subprocess.run(command, capture_output=True, timeout=90)
    (directory / "compile.stdout.bin").write_bytes(process.stdout)
    (directory / "compile.stderr.log").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    return binary


def run_case(binary, scenario):
    directory = Path(tempfile.mkdtemp(prefix=scenario + "-", dir=binary.parent))
    log = directory / "observer.host.log"
    if scenario == "exclusive":
        log.write_bytes(b"existing-run-do-not-overwrite\n")
    environment = dict(os.environ, ASAN_OPTIONS="detect_leaks=1:abort_on_error=1",
                       UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
    process = subprocess.run([str(binary), scenario, str(log)], capture_output=True,
                             env=environment, timeout=30)
    (directory / "stdout.bin").write_bytes(process.stdout)
    (directory / "stderr.log").write_bytes(process.stderr)
    assert process.returncode == 0, process.stderr.decode(errors="replace")
    assert process.stdout == b"", "Evidence must not share the console"
    assert b"Sanitizer" not in process.stderr and b"runtime error:" not in process.stderr
    if scenario == "exclusive":
        assert log.read_bytes() == b"existing-run-do-not-overwrite\n"
        return [], process.stderr
    if not log.exists():
        assert scenario == "badarg"
        return [], process.stderr
    raw = log.read_bytes()
    assert raw.endswith(b"\n")
    lines = raw.splitlines(keepends=True)
    assert len(lines) <= 163 and all(len(line) < 2048 for line in lines)
    rows = []
    for line in lines:
        fields = line.decode("ascii").split()
        row = dict(field.split("=", 1) for field in fields)
        assert len(row) == len(fields), "Duplicate fields make evidence ambiguous"
        assert row["status"] == "native_unverified" and row["identity"] == "unknown"
        assert row["binding"] == "unbound"
        assert row["pid"] == row["tid"] == "unknown"
        assert row["capture"] == row["physical"] == "0x0"
        rows.append(row)
    assert rows[0]["kind"] == "begin"
    assert rows[0]["schema"] == "readonly_scope_v2"
    assert rows[0]["producer_sites"] == "0x2"
    assert rows[0]["producer_quota"] == "0x10"
    assert rows[0]["producer_anchor_length"] == "0x18"
    assert rows[0]["poweron_quota"] == "0x10"
    assert rows[0]["poweron_anchor_length"] == "0x8"
    if not scenario.startswith("poweron_") and scenario != "producer_limits":
        assert not any(row["kind"] == "poweron_context" for row in rows)
        for row in rows:
            if row["kind"] == "end":
                assert row["poweron_records"] == "0x0"
    return rows, process.stderr


def entries(rows):
    return [row for row in rows if row["kind"] == "entry"]


def final(rows):
    assert rows[-1]["kind"] == "end"
    assert sum(row["kind"] == "end" for row in rows) == 1
    assert rows[-1]["close_result"] == "unknown"
    assert int(rows[-1]["poweron_records"], 16) == sum(
        row["kind"] == "poweron_context" for row in rows)
    for site, key in zip(("entry", "pre_M_store"), ("producer0_records", "producer1_records")):
        assert int(rows[-1][key], 16) == sum(
            row["kind"] == "M_producer" and row["site"] == site for row in rows)
    assert int(rows[-1]["producer_sequence"], 16) == sum(row["kind"] == "M_producer" for row in rows)
    return rows[-1]


def check_entry(row, sp_available=True, tokens_available=True):
    base = int(row["candidate_base"], 16)
    slot = int(row["lr_slot"], 16)
    assert base == 0x5500000000
    assert int(row["actual_pc"], 16) == int(row["translated_entry_pc"], 16) == base + 0x2E068CC
    assert int(row["lr"], 16) == int(row["x30"], 16) == base + (0x209EE80, 0x209EE88)[slot]
    assert row["x0"] == "0x1122334455667788"
    assert row["x23"] == "0xf123456789abcdef"
    assert row["x24"] == "0x9988776655443322"
    assert row["cpsr_raw"] == "0xa00003c0"
    assert row["nzcv"] == "0xa0000000" and row["nzcv_mask"] == "0xf0000000"
    assert row["cpsr_m"] == "0x00" and row["context_mode"] == "EL0t"
    for name, raw in (("ttbr0_el1", "0x1234005500456000"),
                      ("tpidr_el0", "0xfedcba9876543210")):
        assert row[name + "_available"] == ("0x1" if tokens_available else "0x0")
        assert row[name + "_read_length"] == ("0x8" if tokens_available else "0x0")
        assert row[name + "_raw"] == (raw if tokens_available else "unknown")
    assert row["api_ok"] == "0x1" and row["vcpu"] == "0x0"
    for name in REGISTERS:
        if name == "sp" and not sp_available:
            assert row["sp"] == "unknown" and row["sp_read_length"] == "0x0"
            continue
        assert row[name + "_read_length"] == ("0x4" if name == "cpsr" else "0x8")
        if name != "cpsr":
            value = row["actual_pc"] if name == "pc" else row[name]
            assert len(value) == 18 and value.startswith("0x")


@pytest.mark.parametrize("scenario", ("success", "sp_absent", "tokens_absent"))
def test_exact_entry_and_architectural_widths(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    assert len(entries(rows)) == 2
    for row in entries(rows):
        check_entry(row, sp_available=scenario != "sp_absent",
                    tokens_available=scenario != "tokens_absent")
    assert final(rows)["stop"] == "none"


@pytest.mark.parametrize("scenario", ("quotas", "interleaved", "fault_budget"))
def test_independent_success_quotas_and_bounded_faults(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    for slot in (0, 1):
        selected = [row for row in entries(rows) if int(row["lr_slot"], 16) == slot]
        assert [int(row["ordinal"], 16) for row in selected] == list(range(1, 17))
        for row in selected:
            check_entry(row)
    end = final(rows)
    assert end["lr0_records"] == end["lr1_records"] == "0x10"
    if scenario == "fault_budget":
        assert end["fault_lines"] == "0x20" and int(end["suppressed_faults"], 16) == 48
    else:
        assert int(end["other_lr"], 16) >= 100 and end["fault_lines"] == "0x0"


@pytest.mark.parametrize("scenario", ("anchor_reject", "cross_tb", "address"))
def test_rejects_partial_tb_shape_bytes_and_addresses(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not entries(rows)
    assert not any(row["kind"] == "candidate" for row in rows)
    end = final(rows)
    assert end["candidate_found"] == "0x0" and end["fault_lines"] == "0x0"
    assert end["faults"] == "0x0000000000000000"


def test_unrelated_low12_collisions_do_not_spend_fault_budget(observer_binary):
    rows, errors = run_case(observer_binary, "noncandidate_after_bound")
    assert errors == b"" and len(entries(rows)) == 2
    assert not any(row["kind"] == "fault" for row in rows)
    assert final(rows)["stop"] == "none" and final(rows)["fault_lines"] == "0x0"


@pytest.mark.parametrize("scenario,cause", [
    ("anchor_changed_bytes", "insn_bytes"), ("anchor_changed_short", "insn_bytes"),
    ("anchor_changed_partial", "partial_tb"), ("anchor_changed_shape", "insn_shape"),
    ("anchor_changed_noncontinuous", "insn_shape"),
])
def test_known_entry_changes_disable_and_invalidate_the_set(observer_binary, scenario, cause):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and len(entries(rows)) == 1
    faults = [row for row in rows if row["kind"] == "fault"]
    assert len(faults) == 1 and faults[0]["reason"] == "anchor_changed"
    assert faults[0]["cause"] == cause
    assert final(rows)["stop"] == "anchor_changed"


@pytest.mark.parametrize("scenario,name,actual,ok", [
    *(("short_" + name, name, 3 if name == "cpsr" else 7, 1) for name in REGISTERS + TOKENS),
    ("api_pc", "pc", 8, 0), ("api_x23", "x23", 8, 0), ("api_cpsr", "cpsr", 4, 0),
    ("api_TTBR0_EL1", "TTBR0_EL1", 8, 0), ("api_TPIDR_EL0", "TPIDR_EL0", 8, 0),
    ("long_cpsr", "cpsr", 8, 1),
])
def test_failed_api_and_exact_length_rejection(observer_binary, scenario, name, actual, ok):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not entries(rows)
    fault = next(row for row in rows if row["kind"] == "fault")
    assert fault["reason"] == "register_read" and fault["reg"] == name
    assert int(fault["read_length"], 16) == actual and int(fault["api_ok"], 16) == ok
    assert int(fault["required_length"], 16) == (4 if name == "cpsr" else 8)
    assert final(rows)["lr0_records"] == "0x0"


@pytest.mark.parametrize("scenario", ("unknown", "duplicate", "null_regs", "empty_regs",
                                      "many_regs", "vcpu_init_limit", "vcpu_reinit",
                                      "vcpu_exec_limit", "pc_mismatch", "stale_pc", "aarch32"))
def test_registry_context_and_vcpu_rejections(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not entries(rows)
    assert any(row["kind"] == "fault" for row in rows)
    assert final(rows)["lr0_records"] == final(rows)["lr1_records"] == "0x0"


def test_kernel_context_is_raw_unbound_observation_not_ap(observer_binary):
    rows, errors = run_case(observer_binary, "kernel_context")
    assert errors == b"" and not [row for row in rows if row["kind"] == "fault"]
    row, = entries(rows)
    assert row["cpsr_raw"] == "0xa00003c5" and row["cpsr_m"] == "0x05"
    assert row["context_mode"] == "other_aarch64"
    assert row["status"] == "native_unverified" and row["binding"] == "unbound"
    assert row["identity"] == row["pid"] == row["tid"] == "unknown"


def test_later_ambiguity_invalidates_earlier_unbound_records(observer_binary):
    rows, errors = run_case(observer_binary, "ambiguity")
    assert errors == b"" and len(entries(rows)) == 1
    end = final(rows)
    assert end["ambiguous"] == "0x1" and end["stop"] == "ambiguous_base"
    assert int(end["conflicting_base"], 16) != int(end["candidate_base"], 16)
    assert sum(row["kind"] == "candidate" for row in rows) == 1


@pytest.mark.parametrize("scenario", ("target", "user_mode", "version", "version_min", "smp", "max_vcpus"))
def test_install_contract_rejects_unsupported_context(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not entries(rows)
    assert final(rows)["stop"] != "none"


@pytest.mark.parametrize("scenario", ("write_failure", "flush_failure", "format_failure", "close_failure"))
def test_host_io_failure_requires_external_rejection(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert b"scope_observer_host_error stage=" in errors
    assert len(errors.splitlines()) == 1
    if scenario == "close_failure":
        assert b"stage=close" in errors and final(rows)["close_result"] == "unknown"
    else:
        assert not any(row["kind"] == "end" for row in rows)


@pytest.mark.parametrize("scenario", ("exclusive", "badarg", "duplicate_install"))
def test_log_arguments_and_exclusive_creation(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert b"scope_observer_host_error" in errors
    if scenario == "duplicate_install":
        assert len(entries(rows)) == 2 and final(rows)["close_result"] == "unknown"


def poweron_entries(rows):
    return [row for row in rows if row["kind"] == "poweron_context"]


def check_poweron(row, base=0x5500000000, tokens_available=True):
    common = {"kind", "status", "identity", "binding", "pid", "tid", "capture", "physical"}
    schema_fields = json.loads((HERE / "log-schema.json").read_text())["kinds"]["poweron_context"]
    assert set(row) == common | set(schema_fields)
    assert row["site"] == "dispatch" and row["vcpu"] == "0x0"
    assert 1 <= int(row["ordinal"], 16) <= 16
    assert int(row["candidate_base"], 16) == base
    assert int(row["actual_pc"], 16) == int(row["translated_entry_pc"], 16) == base + 0x1951844
    assert row["anchor_length"] == "0x8"
    assert row["controller"] == "0x1122334455667788"
    assert row["raw_x2"] == "0xfedcba9801abc090" and row["raw_u32"] == "0x01abc090"
    assert int(row["raw_u32"], 16) == (int(row["raw_x2"], 16) & 0xFFFFFFFF)
    assert (int(row["raw_u32"], 16) & 0xFF000FFF) == 0x01000090
    assert row["caller_raw"] == "0xabcd005500abcdef"
    assert row["cpsr_raw"] == "0xa00003c0" and row["cpsr_m"] == "0x00"
    assert row["context_mode"] == "EL0t"
    assert row["nzcv"] == "0xa0000000" and row["nzcv_mask"] == "0xf0000000"
    for name in POWERON_REGISTERS:
        assert row[name + "_read_length"] == ("0x4" if name == "cpsr" else "0x8")
    for name, raw in (("ttbr0_el1", "0x1234005500456000"),
                      ("tpidr_el0", "0xfedcba9876543210")):
        assert row[name + "_available"] == ("0x1" if tokens_available else "0x0")
        assert row[name + "_raw"] == (raw if tokens_available else "unknown")
        assert row[name + "_read_length"] == ("0x8" if tokens_available else "0x0")
        assert row[name + "_api_ok"] == ("0x1" if tokens_available else "unknown")
    assert row["api_ok"] == "0x1"


@pytest.mark.parametrize("scenario", ("poweron_order_first", "poweron_order_scope_first"))
def test_poweron_and_scope_discovery_and_execution_order_are_independent(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and len(entries(rows)) == 2
    row, = poweron_entries(rows)
    check_poweron(row)
    candidate_index = next(i for i, item in enumerate(rows) if item["kind"] == "candidate")
    poweron_index = rows.index(row)
    assert (poweron_index < candidate_index) == (scenario == "poweron_order_first")
    for item in entries(rows):
        check_entry(item)
    assert final(rows)["poweron_records"] == "0x1" and final(rows)["fault_lines"] == "0x0"


@pytest.mark.parametrize("scenario", ("poweron_exact8", "poweron_no_literal", "poweron_raw_filter",
                                      "poweron_tokens_absent"))
def test_poweron_exact_stub_full_width_context_and_raw_filter(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    row, = poweron_entries(rows)
    check_poweron(row, tokens_available=scenario != "poweron_tokens_absent")
    assert not entries(rows) and final(rows)["candidate_found"] == "0x0"
    assert final(rows)["faults"] == "0x0000000000000000"


@pytest.mark.parametrize("scenario", ("poweron_reject", "poweron_address",
                                      "poweron_noncandidate_after_bound"))
def test_poweron_partial_mutated_cross_tb_and_low12_collisions_are_silent(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not poweron_entries(rows)
    assert not any(row["kind"] == "fault" for row in rows)
    assert final(rows)["poweron_records"] == final(rows)["fault_lines"] == "0x0"
    assert len(entries(rows)) == (2 if scenario == "poweron_noncandidate_after_bound" else 0)
    assert final(rows)["stop"] == "none"


@pytest.mark.parametrize("scenario", ("poweron_quotas", "poweron_after_scope_quotas", "poweron_fault_budget"))
def test_poweron_quota_is_independent_of_both_scope_slots_and_faults(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and len(entries(rows)) == 32
    assert [int(row["ordinal"], 16) for row in poweron_entries(rows)] == list(range(1, 17))
    for row in poweron_entries(rows):
        check_poweron(row)
    for row in entries(rows):
        check_entry(row)
    end = final(rows)
    assert end["lr0_records"] == end["lr1_records"] == end["poweron_records"] == "0x10"
    if scenario == "poweron_fault_budget":
        assert len(rows) == 83 and end["fault_lines"] == "0x20"
        assert int(end["suppressed_faults"], 16) == 48
    else:
        assert end["faults"] == "0x0000000000000000"


@pytest.mark.parametrize("scenario", ("poweron_multiple_bases", "poweron_retranslation"))
def test_poweron_userdata_is_immutable_and_multiple_bases_remain_unbound(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    selected = poweron_entries(rows)
    assert len(selected) == 3
    for row, base in zip(selected, (0x5500000000, 0x5500100000, 0x5500000000)):
        check_poweron(row, base=base)
    assert sum(row["kind"] == "candidate" for row in rows) == 1
    end = final(rows)
    assert end["ambiguous"] == "0x0" and end["stop"] == "none" and end["fault_lines"] == "0x0"


@pytest.mark.parametrize("scenario,name,actual,ok", [
    *(("poweron_short_" + name, name, 3 if name == "cpsr" else 7, 1)
      for name in POWERON_REGISTERS + TOKENS),
    *(("poweron_api_" + name, name, 4 if name == "cpsr" else 8, 0)
      for name in POWERON_REGISTERS + TOKENS),
    ("poweron_long_cpsr", "cpsr", 8, 1),
])
def test_poweron_exact_register_reads_reject_without_spending_success_quota(
        observer_binary, scenario, name, actual, ok):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "register_read" and fault["reg"] == name
    assert int(fault["read_length"], 16) == actual and int(fault["api_ok"], 16) == ok
    assert int(fault["required_length"], 16) == (4 if name == "cpsr" else 8)
    row, = poweron_entries(rows)
    check_poweron(row)
    assert row["ordinal"] == "0x1" and rows.index(fault) < rows.index(row)
    assert final(rows)["poweron_records"] == "0x1"


def test_missing_x2_does_not_disable_or_change_scope_records(observer_binary):
    rows, errors = run_case(observer_binary, "poweron_x2_absent")
    assert errors == b"" and not poweron_entries(rows) and len(entries(rows)) == 2
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "unknown_register" and fault["reg"] == "x2"
    assert fault["required_length"] == "0x8" and fault["read_attempted"] == "0x0"
    assert fault["read_length"] == fault["api_ok"] == "0x0"
    for row in entries(rows):
        check_entry(row)
    assert final(rows)["stop"] == "none"


@pytest.mark.parametrize("scenario,reason", (("poweron_pc_mismatch", "pc_mismatch"),
    ("poweron_stale_pc", "pc_mismatch"), ("poweron_aarch32", "not_aarch64"),
    ("poweron_kernel_context", "poweron_not_el0t"), ("poweron_vcpu_exec_limit", "vcpu_limit")))
def test_poweron_context_rejections_preserve_cpsr_mode_and_do_not_promote_scope(observer_binary, scenario, reason):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not poweron_entries(rows)
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == reason and fault["site"] == "dispatch"
    if scenario == "poweron_kernel_context":
        assert fault["cpsr_raw"] == "0xa00003c5" and fault["cpsr_m"] == "0x05"
        row, = entries(rows)
        assert row["cpsr_raw"] == "0xa00003c5" and row["context_mode"] == "other_aarch64"
    elif scenario == "poweron_aarch32":
        assert fault["cpsr_raw"] == "0xa00003d0" and fault["cpsr_m"] == "0x10"
    assert final(rows)["poweron_records"] == "0x0"


@pytest.mark.parametrize("scenario", ("poweron_write_failure", "poweron_flush_failure"))
def test_poweron_quota_is_consumed_only_after_complete_host_record(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert b"scope_observer_host_error stage=" in errors and len(errors.splitlines()) == 1
    assert not any(row["kind"] == "end" for row in rows)


def test_authoritative_schema_tracks_current_production_source():
    schema_raw = (HERE / "log-schema-v2.json").read_bytes()
    schema = json.loads(schema_raw)
    contract = json.loads((HERE / "source-contract-v2.json").read_bytes())
    # v2 source hashes live in the build receipt; the source contract pins the schema.
    assert schema["schema"] == contract["trace_schema"] == "readonly_scope_v2"
    assert schema["profile"] == contract["profile"] == "qemu-readonly-scope-v2"
    assert contract["schema"] == "readonly_scope_source_contract_v2"
    assert contract["v2_schema_sha256"] == hashlib.sha256(schema_raw).hexdigest()
    assert schema["source"].endswith("report/" + HERE.name + "/scope-observer.c")
    required = {"scope-observer.c", "late-sites.inc", "build-plugin.sh",
                "log-schema-v2.json", "source-contract-v2.json", "check_run_context_v2.py",
                "check_run_context.py", "integration/scope_trace_checks_v2.py",
                "integration/scope_trace_checks.py"}
    assert set(contract["actual_build_source_names_required"]) == required
    assert len(contract["actual_build_source_names_required"]) == len(required)
    assert all((HERE / name).is_file() for name in required)
    legacy_digest = hashlib.sha256((HERE / "log-schema.json").read_bytes()).hexdigest()
    assert schema["inherited_v1_schema_sha256"] == contract["inherited_v1_schema_sha256"] == legacy_digest
    assert legacy_digest == "8b6e2bf3576e7e4e5566fa215d2758e088ae8867ed6b3c36ea7b90f38767e50c"
    assert schema["file_contract"]["maximum_file_lines"] == 163
    assert schema["file_contract"]["poweron_success_quota"] == 16


PRODUCER_KEYS = set("""
site vcpu ordinal producer_sequence callback_phase event_pc gdb_pc_raw candidate_base
scope_anchor_seen anchor_length input_kind x0_raw raw_input_u32 proposed_u32 x30_raw
caller_raw cpsr_raw cpsr_m context_mode nzcv nzcv_mask sp_available sp_raw sp_read_length
sp_api_ok ttbr0_el1_available ttbr0_el1_raw ttbr0_el1_read_length ttbr0_el1_api_ok
 tpidr_el0_available tpidr_el0_raw tpidr_el0_read_length tpidr_el0_api_ok
 gdb_pc_read_length gdb_pc_api_ok x0_read_length x0_api_ok x30_read_length x30_api_ok
cpsr_read_length cpsr_api_ok api_ok
""".split())
PRODUCER_PRE_KEYS = {"x1_raw", "x1_read_length", "x1_api_ok",
                     "effective_destination_raw", "destination_match"}
PRODUCER_REGISTERS = ("pc", "x0", "x30", "cpsr", "sp") + TOKENS


def producers(rows):
    return [row for row in rows if row["kind"] == "M_producer"]


def check_producer(row, optional=True):
    pre = row["site"] == "pre_M_store"
    assert row["site"] in ("entry", "pre_M_store")
    common = {"kind", "status", "identity", "binding", "pid", "tid", "capture", "physical"}
    assert set(row) == common | PRODUCER_KEYS | (PRODUCER_PRE_KEYS if pre else set())
    assert row["vcpu"] == "0x0" and row["callback_phase"] == "before_instruction"
    assert row["candidate_base"] == "0x0000005500000000"
    assert int(row["event_pc"], 16) == 0x5500000000 + (0x276E71C if pre else 0x276E710)
    assert row["gdb_pc_raw"] == "0x0000005502e068cc"
    assert row["event_pc"] != row["gdb_pc_raw"]
    assert row["anchor_length"] == "0x18" and row["input_kind"] == "u32_value"
    assert row["scope_anchor_seen"] in ("0x0", "0x1")
    assert row["x30_raw"] == row["caller_raw"] == "0xabcd005500abcdef"
    assert row["raw_input_u32"] == f'0x{int(row["x0_raw"], 16) & 0xFFFFFFFF:08x}'
    assert row["proposed_u32"] == (row["raw_input_u32"] if pre else "unknown")
    for key in ("x0_raw", "x30_raw", "caller_raw", "gdb_pc_raw", "event_pc", "candidate_base"):
        assert len(row[key]) == 18 and row[key].startswith("0x")
    if pre:
        assert row["x1_raw"] == "0x0000005507e6a4d8"
        assert row["effective_destination_raw"] == "0x0000005507e6a7c8"
        assert int(row["x1_raw"], 16) + 0x2F0 == int(row["effective_destination_raw"], 16)
        assert row["destination_match"] == row["x1_api_ok"] == "0x1"
        assert row["x1_read_length"] == "0x8"
    cpsr = int(row["cpsr_raw"], 16)
    assert len(row["cpsr_raw"]) == 10 and len(row["cpsr_m"]) == 4
    assert int(row["cpsr_m"], 16) == cpsr & 0x1F
    assert cpsr & 0x1F in (0, 4, 5, 8, 9, 12, 13)
    assert int(row["nzcv"], 16) == cpsr & 0xF0000000 and row["nzcv_mask"] == "0xf0000000"
    assert row["context_mode"] == ("EL0t" if cpsr & 0x1F == 0 else "other_aarch64")
    assert row["api_ok"] == "0x1"
    for name in ("gdb_pc", "x0", "x30", "cpsr"):
        assert row[name + "_read_length"] == ("0x4" if name == "cpsr" else "0x8")
        assert row[name + "_api_ok"] == "0x1"
    for name, raw in (("sp", "0x0000007ffffffd00"),
                      ("ttbr0_el1", "0x1234005500456000"),
                      ("tpidr_el0", "0xfedcba9876543210")):
        assert row[name + "_available"] == ("0x1" if optional else "0x0")
        assert row[name + "_raw"] == (raw if optional else "unknown")
        assert row[name + "_read_length"] == ("0x8" if optional else "0x0")
        assert row[name + "_api_ok"] == ("0x1" if optional else "unknown")


@pytest.mark.parametrize("scenario", ("producer_exact", "producer_optional_absent",
                                      "producer_prestore_only", "producer_retranslation"))
def test_producer_exact_callbacks_full64_and_actual_prestore_operand(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    selected = producers(rows)
    assert [row["site"] for row in selected] == (
        ["pre_M_store"] if scenario == "producer_prestore_only" else ["entry", "pre_M_store"])
    for row in selected:
        check_producer(row, optional=scenario != "producer_optional_absent")
        assert row["scope_anchor_seen"] == ("0x1" if scenario == "producer_exact" else "0x0")
    assert selected[-1]["x0_raw"] == "0x11223344cafebabe"
    assert selected[-1]["proposed_u32"] == "0xcafebabe"
    if len(selected) == 2:
        assert selected[0]["x0_raw"] == "0xfeedface80000001"
        assert selected[0]["raw_input_u32"] == "0x80000001"
        assert selected[0]["raw_input_u32"] != selected[-1]["proposed_u32"]
    assert final(rows)["stop"] == "none"


def test_early_producer_rows_are_written_before_scope_and_never_rewritten(observer_binary):
    rows, errors = run_case(observer_binary, "producer_early")
    assert errors == b""
    selected = producers(rows)
    assert [row["scope_anchor_seen"] for row in selected] == ["0x0", "0x0", "0x1", "0x1"]
    candidate, = [row for row in rows if row["kind"] == "candidate"]
    assert rows.index(selected[1]) < rows.index(candidate) < rows.index(selected[2])
    assert [row["producer_sequence"] for row in selected] == ["0x1", "0x2", "0x3", "0x4"]
    assert not any(row["kind"] == "producer_candidate" for row in rows)
    for row in selected:
        check_producer(row)
    assert final(rows)["producer_sequence"] == "0x4"


@pytest.mark.parametrize("scenario", ("producer_reject", "producer_cross_tb", "producer_address",
                                      "producer_anchor_only", "producer_collisions_after_bound"))
def test_producer_complete24_anchor_translation_is_not_execution_and_collisions_are_silent(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not any(row["kind"] == "fault" for row in rows)
    selected = producers(rows)
    assert len(selected) == (1 if scenario == "producer_collisions_after_bound" else 0)
    assert not any(row["kind"] == "producer_candidate" for row in rows)
    end = final(rows)
    assert end["stop"] == "none" and end["fault_lines"] == "0x0"
    assert end["producer_anchor_found"] == ("0x1" if scenario in (
        "producer_anchor_only", "producer_collisions_after_bound") else "0x0")


@pytest.mark.parametrize("scenario,cause", (
    ("producer_scope_conflict", "scope_vs_producer"),
    ("producer_after_scope_conflict", "producer_vs_scope"),
    ("producer_second_base_before_scope", "producer_vs_producer"),
    ("producer_second_base_after_scope", "producer_vs_producer"),
))
def test_producer_scope_and_second_producer_bases_conflict_in_both_orders(observer_binary, scenario, cause):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    assert len(producers(rows)) == (0 if scenario == "producer_after_scope_conflict" else 1)
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "producer_base_conflict" and fault["cause"] == cause
    end = final(rows)
    assert end["ambiguous"] == "0x1" and end["stop"] == "producer_base_conflict"
    assert end["producer_anchor_found"] == "0x1"
    assert int(end["producer_base"], 16) != int(end["producer_conflicting_base"], 16)
    assert {int(end["producer_base"], 16), int(end["producer_conflicting_base"], 16)} == {
        0x5500000000, 0x5500100000}


@pytest.mark.parametrize("scenario,reason", (("producer_scope_anchor_changed", "anchor_changed"),
    ("producer_second_scope", "ambiguous_base")))
def test_existing_scope_invalidation_also_stops_producer_callbacks(observer_binary, scenario, reason):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and len(producers(rows)) == 1
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == reason and final(rows)["stop"] == reason


@pytest.mark.parametrize("suffix,cause", (("partial", "partial_tb"), ("shape", "insn_shape"),
    ("short", "insn_bytes"), ("noncontinuous", "insn_shape"),
    ("second_store", "insn_bytes"), ("ret", "insn_bytes")))
def test_known_producer_changes_include_uninstrumented_second_store_and_ret(observer_binary, suffix, cause):
    rows, errors = run_case(observer_binary, "producer_changed_" + suffix)
    assert errors == b"" and len(producers(rows)) == 1
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "producer_anchor_changed" and fault["cause"] == cause
    assert final(rows)["stop"] == "producer_anchor_changed"


@pytest.mark.parametrize("site,name", [(site, name) for site in ("entry", "pre")
    for name in PRODUCER_REGISTERS + ("x1",) if site == "pre" or name != "x1"])
@pytest.mark.parametrize("failure", ("short", "api", "false7", "long"))
def test_producer_each_failed_present_read_rejects_whole_row_without_spending_success(
        observer_binary, site, failure, name):
    scenario = f"producer_{site}_{failure}_{name}"
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "register_read" and fault["reg"] == name
    required = 4 if name == "cpsr" else 8
    assert int(fault["required_length"], 16) == required
    length = required if failure == "api" else (8 if name == "cpsr" else 9) if failure == "long" else required - 1
    assert int(fault["read_length"], 16) == length
    assert int(fault["api_ok"], 16) == (0 if failure in ("api", "false7") else 1)
    row, = producers(rows)
    check_producer(row)
    assert row["ordinal"] == row["producer_sequence"] == "0x1"
    assert row["site"] == ("entry" if site == "entry" else "pre_M_store")
    assert rows.index(fault) < rows.index(row) and final(rows)["producer_sequence"] == "0x1"


@pytest.mark.parametrize("name", ("pc", "x0", "x30", "cpsr"))
def test_producer_missing_required_descriptor_rejects_initialization(observer_binary, name):
    rows, errors = run_case(observer_binary, "producer_missing_" + name)
    assert errors == b"" and not producers(rows)
    assert any(row["kind"] == "fault" and row["reason"] == "unknown_register" and row["reg"] == name
               for row in rows)
    assert final(rows)["stop"] == "unknown_register"


def test_missing_x1_rejects_prestore_callback_and_preserves_entry(observer_binary):
    rows, errors = run_case(observer_binary, "producer_x1_absent")
    assert errors == b"" and [row["site"] for row in producers(rows)] == ["entry", "entry"]
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == "unknown_register" and fault["reg"] == "x1"
    assert fault["read_attempted"] == fault["read_length"] == fault["api_ok"] == "0x0"
    assert final(rows)["producer1_records"] == "0x0"


@pytest.mark.parametrize("scenario,reason", (
    ("producer_bad_destination", "producer_destination_mismatch"),
    ("producer_destination_overflow", "producer_destination_overflow")))
def test_producer_checks_destination_arithmetic_without_dereferencing_it(observer_binary, scenario, reason):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["reason"] == reason and fault["site"] == "pre_M_store"
    row, = producers(rows)
    check_producer(row)
    assert row["ordinal"] == "0x1" and final(rows)["producer_sequence"] == "0x1"


@pytest.mark.parametrize("scenario", ("producer_aarch32", "producer_reserved", "producer_modes"))
def test_producer_modes_preserve_raw_and_never_promote_identity(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    selected = producers(rows)
    for row in selected:
        check_producer(row)
    if scenario == "producer_modes":
        assert [int(row["cpsr_m"], 16) for row in selected] == [m for m in (0, 4, 5, 8, 9, 12, 13) for _ in range(2)]
        assert selected[0]["x0_raw"] == "0xfeedface00000000" and selected[0]["raw_input_u32"] == "0x00000000"
        assert selected[1]["x0_raw"] == "0x11223344ffffffff" and selected[1]["proposed_u32"] == "0xffffffff"
        assert final(rows)["fault_lines"] == "0x0"
    else:
        faults = [row for row in rows if row["kind"] == "fault"]
        assert len(faults) == 2 and all(row["reason"] == "not_aarch64" for row in faults)
        assert {row["cpsr_m"] for row in faults} == {"0x10" if scenario == "producer_aarch32" else "0x02"}
        assert len(selected) == 2 and final(rows)["producer_sequence"] == "0x2"


@pytest.mark.parametrize("scenario,reason", (("producer_vcpu", "vcpu_limit"),
    ("producer_invalid_metadata", "invalid_callback_context")))
def test_producer_callback_context_failures_disable_without_reads(observer_binary, scenario, reason):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b"" and not producers(rows)
    fault, = [row for row in rows if row["kind"] == "fault"]
    assert fault["site"] == "M_producer" and fault["reason"] == reason
    assert final(rows)["stop"] == reason


@pytest.mark.parametrize("scenario", ("producer_limits", "producer_longest"))
def test_producer_17_calls_only16_success_independent_quotas_and_actual_c_formatter_bound(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert errors == b""
    selected = producers(rows)
    assert len(selected) == 32
    for site in ("entry", "pre_M_store"):
        assert [int(row["ordinal"], 16) for row in selected if row["site"] == site] == list(range(1, 17))
    for row in selected:
        check_producer(row)
    end = final(rows)
    assert end["producer0_records"] == end["producer1_records"] == "0x10"
    assert end["producer_sequence"] == "0x20"
    if scenario == "producer_limits":
        assert len(rows) == 163 and end["fault_lines"] == "0x20"
        assert int(end["suppressed_faults"], 16) == 48
        assert end["lr0_records"] == end["lr1_records"] == end["poweron_records"] == "0x10"
        assert end["late0_records"] == end["late1_records"] == end["late2_records"] == "0x10"
        assert end["late_sequence"] == "0x30"
    else:
        raw = " ".join(f"{key}={value}" for key, value in selected[-1].items()) + "\n"
        assert len(raw.encode("ascii")) == 1168
        assert end["fault_lines"] == "0x0"


@pytest.mark.parametrize("scenario", ("producer_write_failure", "producer_flush_failure"))
def test_producer_io_failure_never_advances_c_success_or_sequence_counters(observer_binary, scenario):
    rows, errors = run_case(observer_binary, scenario)
    assert b"scope_observer_host_error stage=" in errors and len(errors.splitlines()) == 1
    assert not any(row["kind"] == "end" for row in rows)


def test_source_uses_only_reviewed_readonly_plugin_surface():
    source = (HERE / "scope-observer.c").read_text() + (HERE / 'late-sites.inc').read_text()
    forbidden = ("QEMU_PLUGIN_CB_RW_REGS", "qemu_plugin_write_", "qemu_plugin_set_pc",
                 "qemu_plugin_read_memory_", "qemu_plugin_translate_vaddr", "qemu_plugin_outs",
                 "qemu_plugin_register_vcpu_syscall", "qemu_plugin_update_ns",
                 "qemu_plugin_register_vcpu_mem", "qemu_plugin_insn_haddr")
    assert not any(token in source for token in forbidden)
    import re
    calls = set(re.findall(r"\b(qemu_plugin_\w+)\s*\(", source)) - {"qemu_plugin_install"}
    assert calls == {"qemu_plugin_" + name for name in (
        "get_registers", "read_register", "register_vcpu_init_cb", "register_vcpu_tb_trans_cb",
        "register_vcpu_insn_exec_cb", "register_atexit_cb", "tb_n_insns", "tb_get_insn",
        "insn_vaddr", "insn_size", "insn_data")}
    from xml.etree import ElementTree
    header = (QEMU / "include/plugins/qemu-plugin.h").read_text()
    assert re.search(r"#define\s+QEMU_PLUGIN_VERSION\s+7\b", header)
    tree = ElementTree.parse(QEMU / "gdbstub/gdb-xml/aarch64-core.xml")
    widths = {reg.attrib["name"]: int(reg.attrib["bitsize"]) for reg in tree.findall("reg")}
    assert all(widths[name] == (32 if name == "cpsr" else 64)
               for name in set(REGISTERS + POWERON_REGISTERS))
    helper = (QEMU / "target/arm/helper.c").read_text()
    for name in TOKENS:
        assert '.name = "' + name + '"' in helper
        assert '"' + name + '"' in source
