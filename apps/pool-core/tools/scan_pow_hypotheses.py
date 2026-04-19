#!/usr/bin/env python3
import json
import sys
import argparse
from pathlib import Path
from typing import Any

sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    from pepepow_pow import blake3_hash, hoohash_v110
except ImportError:
    print("Error: Could not import pepepow_pow.")
    sys.exit(1)

def run_pow(header80, s_mask, n_endian, h_mask):
    seed = blake3_hash(header80[:s_mask] + (b"\x00" * (80 - s_mask)))
    nonce = int.from_bytes(header80[76:80], byteorder=n_endian, signed=False)
    h_hash = blake3_hash(header80[:h_mask] + (b"\x00" * (80 - h_mask)))
    return hoohash_v110(seed, h_hash, nonce)

def replay_evidence(record: dict[str, Any]):
    header80 = bytes.fromhex(record["header80Hex"])
    target_int = int(record["shareTarget"], 16)
    
    # Hypothesis 1: Reversed Merkle Root
    h80_rev_merkle = bytearray(header80)
    h80_rev_merkle[36:68] = h80_rev_merkle[36:68][::-1]
    h80_rev_merkle = bytes(h80_rev_merkle)
    
    variants = [
        ("canonical", header80, 76, "little", 80),
        ("rev_merkle", h80_rev_merkle, 76, "little", 80),
        ("rev_merkle_seed_full", h80_rev_merkle, 80, "little", 80),
        ("rev_merkle_nonce_be", h80_rev_merkle, 76, "big", 80),
    ]

    for name, h80, s_mask, n_endian, h_mask in variants:
        res = run_pow(h80, s_mask, n_endian, h_mask)
        if int.from_bytes(res, "big") <= target_int:
            print(f"!!! HIT !!! {name} | Job: {record.get('jobId')}")
            return True
    return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input")
    args = parser.parse_args()
    
    with open(args.input, "r") as f:
        for idx, line in enumerate(f):
            if not line.strip(): continue
            if replay_evidence(json.loads(line)): return
            if idx % 500 == 0: sys.stderr.write(f"Proc {idx}...\n")

if __name__ == "__main__":
    main()
