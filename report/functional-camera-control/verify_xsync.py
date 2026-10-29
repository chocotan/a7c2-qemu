#!/usr/bin/env python3
"""Offline original-table and actual C-owner POD checks; never opens a VM."""
import argparse
import errno
import hashlib
import json
from pathlib import Path
import re
import struct

HERE = Path(__file__).resolve().parent
NATIVE = HERE.parent.parent
TABLE_SHA256 = "a387e2fc4d3fb45047f8f93d5064b575f04d74ac6998dabb6564775d98b75e90"
FIELDS = ("xsync_defined", "xsync_source_fps", "xsync_word", "xsync_half", "xsync_source_generation")


def require(condition, message):
    if not condition:
        raise ValueError(message)


def original_table():
    pins = json.loads((HERE / "source-pins.json").read_text())
    table = pins["ap"]["table"]
    rows = table["raw_rows_hex"]
    require(len(rows) == 73 and all(re.fullmatch(r"[0-9a-f]{24}", row) for row in rows), "73 original rows")
    raw = bytes.fromhex("".join(rows))
    require(len(raw) == table["bytes"] == 876 and table["rows"] == 73, "original table size")
    require(hashlib.sha256(raw).hexdigest() == table["sha256"] == TABLE_SHA256, "original table digest")
    decoded = list(struct.iter_unpack("<HHII", raw))
    require(all(padding == 0 for half, padding, word, value in decoded), "original padding")
    require([value for half, padding, word, value in decoded] == list(range(78, 5, -1)), "original enum order")
    tuples = {(word, half) for half, padding, word, value in decoded}
    require(len(tuples) == 73 and (0, 0) not in tuples and (0, 2) in tuples, "canonical tuple identity")
    return pins, raw, tuples


def canonical_domain():
    _, _, tuples = original_table()
    return {word for word, half in tuples if half == 1 and 1 <= word <= 120}


def verify_source(app_fw=None):
    pins, raw, tuples = original_table()
    domain = sorted(word for word, half in tuples if half == 1 and 1 <= word <= 120)
    require(domain == [1, 2, 4, 5, 6, 8, 10, 13, 15, 20, 25, 30, 40, 45, 50, 60, 80, 90, 100], "integer clock intersection")
    require(domain == pins["functional_policy"]["canonical_fps_domain"], "policy domain")
    control = (NATIVE / "runtime/analysis/device-models/functional-camera-control.c").read_text()
    declared = re.search(r"canonical_fps\[\]\s*=\s*\{([^}]+)\}", control)
    require(declared is not None and [int(v.strip()) for v in declared[1].split(",")] == domain, "C exact table intersection")
    verified = False
    if app_fw is not None:
        path = Path(app_fw)
        require(path.stat().st_size == pins["ap"]["bytes"], "original AP size")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
            require(digest.hexdigest() == pins["ap"]["sha256"], "original AP identity")
            stream.seek(int(pins["ap"]["table"]["raw"], 16))
            require(stream.read(len(raw)) == raw, "original AP all 73 table rows")
            converter = pins["ap"]["converter"]
            stream.seek(int(converter["raw"], 16))
            require(hashlib.sha256(stream.read(converter["bytes"])).hexdigest() == converter["sha256"], "original converter")
            call = pins["ap"]["mode1_call"]
            stream.seek(int(call["raw"], 16))
            instruction = stream.read(4)
            require(instruction.hex() == call["hex"], "original mode1 call bytes")
            opcode = int.from_bytes(instruction, "little")
            displacement = opcode & 0x3ffffff
            if displacement & 0x2000000:
                displacement -= 0x4000000
            require(opcode >> 26 == 0b100101 and int(call["va"], 16) + displacement * 4 == int(call["target"], 16), "original BL target")
        verified = True
    return {"original_table_rows": 73, "canonical_fps_domain": domain, "original_AP_verified": verified,
            "software_timing_defined": True, "physical_xsync_verified": False, "flash_trigger_implemented": False}


def state_bytes(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{256}", value) is not None, "State128 hex")
    return bytes.fromhex(value)


def u32(raw, offset):
    return struct.unpack_from("<I", raw, offset)[0]


def u64(raw, offset):
    return struct.unpack_from("<Q", raw, offset)[0]


def state_error(raw):
    if u32(raw, 0) != 1 or u32(raw, 4) != 15 or u64(raw, 120):
        return -errno.EPROTO
    if not u64(raw, 48) or not 1 <= u64(raw, 56) <= 0xffffffff:
        return -errno.ESTALE
    if (not 1 <= u32(raw, 8) <= 8192 or not 1 <= u32(raw, 12) <= 8192 or
            not 1 <= u32(raw, 16) <= 120 or not 1 <= u32(raw, 20) <= 100 or
            u32(raw, 24) not in (400, 800, 1600) or not u32(raw, 28) or not u64(raw, 32) or
            u64(raw, 40) != 0xffffffffffffffff and u64(raw, 40) < 100000):
        return -errno.ERANGE
    if (not u64(raw, 64) or not u64(raw, 112) or u64(raw, 72) > u64(raw, 64) or
            u64(raw, 80) > u64(raw, 72) or u64(raw, 88) > u64(raw, 72)):
        return -errno.EPROTO
    if u32(raw, 104) or u32(raw, 108):
        return -errno.EBUSY
    return 0


def validate_fixture(pod):
    """Consume the C fixture's actual State128, saved fields, record and full wire."""
    integers = {"result", "probe_rc", "bridge_rc", *FIELDS, "config_generation", "published_generation", "shadow_generation",
                "projected_blocks", "zero_policy_blocks", "mode1_requests", "mode1_cycle_id"}
    require(type(pod) is dict and set(pod) == integers | {"model_state", "probe_state", "wire", "record"}, "exact POD fields")
    require(all(type(pod[name]) is int for name in integers), "POD integer fields")
    require(all(pod[name] >= 0 for name in integers - {"result", "probe_rc", "bridge_rc"}), "nonnegative facts")
    model, probe = state_bytes(pod["model_state"]), state_bytes(pod["probe_state"])
    require(state_error(model) == 0 and pod["config_generation"] == u64(model, 56), "validated model state/generation")
    require(u64(probe, 48) == u64(model, 48), "same actual model instance")
    require(isinstance(pod["record"], str), "actual record")
    for name in FIELDS:
        values = re.findall(r"(?:^| )" + name + r"=(\d+)(?= |$)", pod["record"])
        require(len(values) == 1 and int(values[0]) == pod[name], "actual record " + name)
    require(pod["record"].endswith("original_getters_executed=0 original_source_proof=0 EE=0 frame=0 capture=0"), "record not truncated")
    require(pod["bridge_rc"] == 0 and pod["probe_rc"] == pod["result"], "actual bridge/probe result")
    domain = canonical_domain()
    require(pod["xsync_defined"] in (0, 1), "defined flag")
    if pod["xsync_defined"]:
        require(pod["xsync_source_fps"] in domain and pod["xsync_word"] == pod["xsync_source_fps"] and pod["xsync_half"] == 1, "saved canonical capability")
        require(0 < pod["xsync_source_generation"] == pod["published_generation"] <= pod["config_generation"], "saved source generation")
        require((pod["projected_blocks"], pod["zero_policy_blocks"]) == (3, 72), "projection counts")
    else:
        require(all(pod[name] == 0 for name in FIELDS), "undefined fields remain zero")
        require(pod["published_generation"] == pod["projected_blocks"] == pod["zero_policy_blocks"] == 0, "no rejected publication")
    require(isinstance(pod["wire"], str), "wire hex")
    if pod["result"] == 0:
        require(state_error(probe) == 0 and probe == model, "successful actual STATE")
        require(pod["xsync_defined"] == 1 and pod["xsync_source_fps"] == u32(model, 16) and pod["xsync_source_generation"] == u64(model, 56), "current clock source")
        require(re.fullmatch(r"[0-9a-f]{3496}", pod["wire"]) is not None, "full 1748-byte packet")
        wire = bytes.fromhex(pod["wire"])
        require(wire[:8] == bytes.fromhex("0600402000000000"), "outer header")
        require(wire[0x664:0x674] == struct.pack("<HHIIHH", 6, 0x20a6, 0, u32(model, 16), 1, 0), "20a6 exact bytes")
        require(pod["shadow_generation"] < pod["published_generation"] and pod["mode1_requests"] > 0, "not yet consumed publication")
    else:
        require(pod["wire"] == "", "refusal sent no new full")
        if pod["result"] == -errno.ENOTSUP:
            require(state_error(probe) == 0 and probe == model and u32(probe, 16) not in domain, "unsupported exact cadence")
        elif pod["result"] == -errno.ERANGE:
            require(state_error(probe) == -errno.ERANGE, "invalid actual STATE")
        elif pod["result"] == -errno.ESTALE:
            require(state_error(probe) == 0 and probe[:48] != model[:48] and u64(probe, 56) == u64(model, 56), "same-generation config mutation")
        else:
            raise ValueError("unexpected focused refusal")
    return pod


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-fw", type=Path, help="read-only public ALLLANG appFw.so identity/table/call check")
    parser.add_argument("--fixture", type=Path, help="JSONL emitted by the actual C owner fixture")
    args = parser.parse_args()
    result = verify_source(args.app_fw)
    if args.fixture is not None:
        observations = [json.loads(line) for line in args.fixture.read_text().splitlines()]
        require(bool(observations), "actual fixture observations")
        for observation in observations:
            validate_fixture(observation)
        result["C_fixture_observations"] = len(observations)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
