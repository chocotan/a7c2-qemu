"""Authenticate the public assets; choose a repository explicitly, with no fallback."""
import hashlib
import json
from pathlib import Path

POLICIES = {"primary": "primary", "public-secondary-virtual-property-v1": "secondary_virtual"}


def load_public_bank(base, policy):
    """Return authenticated bank bytes and source metadata, never native RAM evidence."""
    if policy not in POLICIES:
        raise ValueError("explicit primary or public-secondary-virtual-property-v1 policy required")
    base = Path(base)
    pins = json.loads((base / "report/cp-start-state-provider/source-pins.json").read_text())
    cp = (base / "runtime/analysis/menu-root/cp/cpapp-b.bin").read_bytes()
    if len(cp) != pins["CP_bytes"] or hashlib.sha256(cp).hexdigest() != pins["CP_sha256"]:
        raise ValueError("public CP identity mismatch")
    seed = (base / "runtime/analysis/unpacked/firmware.tar_unpacked/0110_backup/"
            "SYSIPSX-DSLR/PP/CX89701_ALLLANG.bin").read_bytes()
    if (len(seed) != pins["public_seed_bytes"] or
            hashlib.sha256(seed).hexdigest() != pins["public_seed_sha256"]):
        raise ValueError("public ALLLANG seed identity mismatch")
    selected = pins[POLICIES[policy]]
    bank = seed[selected["offset"]:selected["offset"] + selected["size"]]
    if len(bank) != selected["size"] or hashlib.sha256(bank).hexdigest() != selected["sha256"]:
        raise ValueError("selected public bank identity mismatch")
    return bank, dict(selected, selected_policy=policy,
                     native_repository_selected=False, runtime_consumed=False)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", choices=POLICIES, required=True)
    parser.add_argument("--base", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    _, metadata = load_public_bank(args.base, args.policy)
    print(json.dumps(metadata, indent=2))
