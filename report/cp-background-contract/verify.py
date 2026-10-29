#!/usr/bin/env python3
"""Read-only, stdlib-only verification of the supported CP background frontier."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys


BIAS = 0x108000
SIZE = 18090880
SHA256 = "f5a477588698ef965748903b8959a39ce4f59ffd4aee4d4234ef1670f56a1428"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def verify(path):
    with path.open("rb") as source:
        data = source.read(SIZE + 1)
    require(len(data) == SIZE, "unsupported CP length")
    require(hashlib.sha256(data).hexdigest() == SHA256, "unsupported CP SHA256")

    def raw(address, size):
        require(0 < size and 0 <= address <= len(data) - size, "range outside original CP")
        return data[address:address + size]

    def va(address, size):
        return raw(address - BIAS, size)

    def pin(address, expected):
        require(raw(address, len(bytes.fromhex(expected))) == bytes.fromhex(expected),
                f"original byte mismatch at RAW {address:x}")

    paths = []
    for address, expected_from, expected_to, words in (
        (0xc8ec20, 0, 0x57,
         [0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700, 0x900,
          0xa00, 0xb01, 0xc06, 0xd00, 0x8000, 0x108, 0x8001]),
        (0xc8ec30, 0x57, 0,
         [0x100, 0x200, 0x300, 0x400, 0x500, 0x600, 0x700, 0x900,
          0xa00, 0xb01, 0xd00, 0x8000]),
    ):
        current, target, pointer, count = struct.unpack("<4I", raw(address, 16))
        require((current, target, count) == (expected_from, expected_to, len(words)),
                "unexpected transition descriptor")
        decoded = list(struct.unpack("<" + "H" * count, va(pointer, count * 2)))
        require(decoded == words, "unexpected module sequence")
        paths.append({"from": current, "to": target, "modules": decoded})
    require(va(0xeda43e, 6) == bytes.fromhex("020057000000"), "unexpected cold path")

    pin(0xa173b4, "130a00eb4303da82")  # S+16+2*h versus S+18+2*i: i=h-1.
    pin(0xa173ce, "00eb4100008b7047")
    pin(0xa173d6, "00eb4100408e7047")
    pin(0x3b75f4, "8888a0f58070592800f26881dfe810f0")
    # TBH uses PC=4bf604. Its data is not decoded as Thumb instructions.
    targets = {}
    for descriptor, expected in ((0x100, 0x4bf89a), (0x108, 0x4bf846)):
        offset, = struct.unpack("<H", va(0x4bf604 + 2 * (descriptor - 0x100), 2))
        target = 0x4bf604 + 2 * offset
        require(target == expected, "unexpected slot0 completion branch")
        targets[f"{descriptor:04x}"] = f"{target:x}"
    pin(0x3b7846, "67f2eaf525e0")  # BL b2741e; branch to result test.
    pin(0x3b7898, "e0b1d8f8000004301ce0")
    pin(0x3b78d4, "d8f80c0000f6a4300088")  # Otherwise preserve old completion.
    pin(0xa20b6c, "b0f5897f09d1")  # Special predicate accepts only descriptor112.
    pin(0xa20b86, "00207047")

    params = {}
    for descriptor, expected in ((0x100, (0x18e60f08, 0x128020, 0)),
                                 (0x108, (0x18a60f08, 0x128020, 0))):
        value = struct.unpack("<3I", va(0xe797a8 + 12 * (descriptor & 0xff), 12))
        require(value == expected, "unexpected local parameter block")
        params[f"{descriptor:04x}"] = [f"{word:08x}" for word in value]

    pin(0xa1f41e, "43f6a8100022c0f2a51011460d220c29fbd08a01825a42b9")
    pin(0xa1f436, "00eb8112527922b94a1c482af1d30120704700207047")
    # Actual free clears backing flags only after its resource-specific cleanup.
    pin(0x3b43d4, "00204ff0ff3188f8040088f80500c8e90300")
    names = []
    for index in range(72):
        identity, pointer = struct.unpack("<2I", va(0xe79c90 + 8 * index, 8))
        require(identity == index, "unexpected resource identity")
        encoded = va(pointer, min(96, len(data) - (pointer - BIAS)))
        require(b"\0" in encoded, "unterminated resource name")
        name = encoded.split(b"\0", 1)[0]
        require(name and all(32 <= c < 127 for c in name), "invalid resource name")
        names.append(name.decode("ascii"))
    require(names[12] == "SGC1", "unexpected excluded resource identity")
    pin(0x3abb0a, "3078")  # Type dispatch reads byte0, not uninitialized byte1.
    request_case, = struct.unpack("<H", va(0x4b6090 + 2 * 7, 2))
    require(0x4b6090 + 2 * request_case == 0x4b6120, "unexpected 3007 input dispatch")
    pin(0x3ae120, "042003e1")  # event4 -> common construction, no tail copy.
    pin(0x3ae32c, "0590002604966868cde90604")

    # Slot10's actual producer writes a full u16, then applies control policy.
    pin(0x3d1f28, "4ff65061")
    pin(0x3d1f36, "c0f27211085c0c46")
    pin(0x3d1f76, "a046")
    pin(0x3d4d20, "4ff6506b44f63861c0f2721b")
    pin(0x3d506e, "43f652500beb00014ef6e870c0f2731095f26eff")
    pin(0x66af64, "00202268d38a0b80")
    policy = list(struct.iter_unpack("<HBB", va(0xec91f8, 24)))
    require(policy == [(0xb00, 1, 0), (0xb01, 0, 0), (0xb10, 2, 0),
                       (0xb11, 4, 0), (0xb12, 5, 0), (0xb20, 6, 0)],
            "unexpected slot10 policy mapping")
    pin(0x66afe4, "83f4d2bf")
    pin(0x2ef050, "50b1012812d1")
    pin(0x2ef068, "48f678200021c0f20e100173")
    pin(0x2ef074, "c0e90011816057e2")
    pin(0x2ef52c, "07b0bde8000ff0bd")

    # Slot11 normalizes and publishes a real record, rather than reading request.
    require(va(0x1107178, 4) == bytes.fromhex("03000000"), "unexpected mode initializer")
    pin(0x2da570, "008ba0f601410a2911d8dfe801f0")
    entry = va(0x3e257e + 5, 1)[0]
    require(0x3e257e + 2 * entry == 0x3e25c2, "unexpected 0c06 normalization")
    pin(0x2da5c2, "40f6064007e0")
    pin(0x2da5d8, "adf85400")
    pin(0x989b9c, "4822c0f2a014d4f8900000f00100")
    pin(0x989bb2, "8cf72ce5d4f890000130c4f89000")
    pin(0x989bc2, "43f628500122c0f2a010d0f8901022ea010101ebc10100ebc1007047")
    return {
        "verified": True, "scope": "offline-original-ROM-contract-only",
        "request_ignored_bytes": {"reserved": 1, "unused_tail": [8, 24]},
        "sha256": SHA256, "paths": paths, "local_parameters": params,
        "slot0_completion_targets": targets,
        "sync_resources": {"count": 72, "stride": 64, "excluded_index": 12,
                           "fields": {"u16": 0, "u8": 5}, "names": names},
        "slot10": {"requested_offset": 0x16, "normal_completion_offset": 0x3d52,
                   "policy_pairs": [[descriptor, mode] for descriptor, mode, _ in policy],
                   "runtime_guard_inputs_proven": False},
        "slot11": {"file_mode_initializer": 3, "snapshot_bytes": 72,
                   "state_offset": 0x24, "normalized_0c06": 0xc06,
                   "runtime_mode_and_cold_feedback_proven": False},
        "runtime_current_proven": False, "success_backend_implemented": False,
        "common_preparation_closed": False, "firmware_recovery_passed": False,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cp", type=Path, default=Path(__file__).resolve().parents[2] /
                        "runtime/analysis/menu-root/cp/cpapp-b.bin")
    args = parser.parse_args()
    try:
        result = verify(args.cp)
    except (OSError, ValueError, struct.error) as error:
        print(json.dumps({"verified": False, "error": str(error)}), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
