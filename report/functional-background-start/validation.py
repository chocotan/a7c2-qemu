#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Read-only check of three inherited public source windows; never CP execution."""
from hashlib import sha256
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]


def verify():
    pins = json.loads((HERE / "source-pins.json").read_text())
    files = {}
    checked = []
    for row in pins["windows"]:
        path = BASE / row["path"]
        if path not in files:
            data = path.read_bytes()
            if len(data) != row["file_bytes"] or sha256(data).hexdigest() != row["file_sha256"]:
                raise ValueError(f"unsupported public original: {path}")
            files[path] = data
        data = files[path]
        offset = int(row["file_offset"], 0)
        raw = data[offset:offset + row["size"]]
        if len(raw) != row["size"] or raw.hex() != row["hex"] or sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError(f"source window mismatch: {row['name']}")
        va = int(row["va"], 0)
        if va - offset != (0x108000 if path.suffix == ".bin" else 0):
            raise ValueError("coordinate mismatch")
        checked.append({"name": row["name"], "bytes": len(raw), "sha256": row["sha256"]})
    if len(checked) != 3:
        raise ValueError("expected exactly three bounded source windows")
    caller = bytes.fromhex(pins["windows"][0]["hex"])
    call_offset = 0xeda4c - 0xed9e0
    if caller[call_offset:call_offset + 4] != bytes.fromhex("39b3fd97"):
        raise ValueError("original eda4c send call fingerprint differs")
    return {"source_windows_verified": True, "windows": checked,
            "bounded_bytes": sum(row["bytes"] for row in checked),
            "original_execution_verified": False, "physical_asic_verified": False,
            "native_predecessors_verified": False, "capture_verified": False}


if __name__ == "__main__":
    print(json.dumps(verify(), indent=2))
