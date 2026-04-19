#!/usr/bin/env python3
import json
import hashlib
from pathlib import Path
import sys

# Add the parent directory to sys.path to import from pool-core
sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    from pepepow_pow import blake3_hash, hoohash_v110
except ImportError:
    print("Error: Could not import pepepow_pow.")
    sys.exit(1)

def dsha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def sha256(data):
    return hashlib.sha256(data).digest()

def blake3(data):
    return blake3_hash(data)

def apply_merkle_branch(leaf_hash, branch, hash_fn):
    root = leaf_hash
    for sibling_hex in branch:
        sibling = bytes.fromhex(sibling_hex)[::-1]
        root = hash_fn(root + sibling)
    return root

def run_probe(record):
    header80_hex = record.get("header80Hex")
    if not header80_hex: return
    
    header80 = bytes.fromhex(header80_hex)
    coinb1 = record.get("coinb1") or ""
    coinb2 = record.get("coinb2") or ""
    en1 = record.get("extranonce1") or ""
    en2 = record.get("extranonce2") or ""
    branch = record.get("merkleBranch") or []
    
    # We don't have all these fields in the record usually if it's minimal.
    auth_hash = record.get("independentAuthoritativeShareHash") or record.get("localComputedHash")
    target = record.get("shareTarget")
    if not target: return
    
    nonce_le = int.from_bytes(header80[76:80], "little")
    nonce_be = int.from_bytes(header80[76:80], "big")
    
    print(f"Record Timestamp: {record.get('timestamp')}")
    print(f"Target: {target}")
    
    # Variations to try:
    seeds = []
    # Masking variants
    for mask_len in [64, 68, 72, 76, 80]:
        masked = header80[:mask_len] + (b"\x00" * (80 - mask_len))
        seeds.append((f"blake3_mask_{mask_len}", blake3(masked)))
    
    # Hash variants
    hashes = []
    hashes.append(("blake3_full", blake3(header80)))
    hashes.append(("blake3_mask_76", blake3(header80[:76] + b"\x00\x00\x00\x00")))
    
    # Nonce variants
    nonces = [("little", nonce_le), ("big", nonce_be)]
    
    # NEW: 64-bit nonce hypothesis
    if en2:
        en2_bytes = bytes.fromhex(en2)
        # Try different combinations of en2 and nonce
        n_bytes = bytes.fromhex(record.get("nonce"))
        nonces.append(("64bit_en2_nonce_le", int.from_bytes(en2_bytes + n_bytes, "little")))
        nonces.append(("64bit_nonce_en2_le", int.from_bytes(n_bytes + en2_bytes, "little")))
    
    for s_name, seed in seeds:
        for h_name, h_hash in hashes:
            for n_name, n_val in nonces:
                # Try all combinations of reversed seed and hash
                for s_rev in [False, True]:
                    for h_rev in [False, True]:
                        s_inp = seed[::-1] if s_rev else seed
                        h_inp = h_hash[::-1] if h_rev else h_hash
                        res = hoohash_v110(s_inp, h_inp, n_val).hex()
                        if int(res, 16) <= int(target, 16):
                            label = f"Seed:{s_name}{'_rev' if s_rev else ''} Hash:{h_name}{'_rev' if h_rev else ''} Nonce:{n_name}"
                            print(f"!!! HIT !!! {label} Result:{res}")
    
    # Hypothesis: Miner DOES NOT reverse some fields in the header
    # Standard: nonce_le = reversed bytes, value = int(bytes, 'little')
    # Alternative: nonce_bytes = as is, value = int(bytes, 'big')
    
    n_bytes_raw = bytes.fromhex(record.get("nonce"))
    ntime_bytes_raw = bytes.fromhex(record.get("ntime"))
    # (Leaving bits alone for now as they are harder to vary)
    
    # Try header with raw (unreversed) fields
    h80_raw = bytearray(header80)
    h80_raw[68:72] = ntime_bytes_raw
    h80_raw[76:80] = n_bytes_raw
    h80_raw = bytes(h80_raw)
    
    nonce_val_raw = int(record.get("nonce"), 16)
    
    # Try this combo
    seed_raw = blake3(h80_raw[:76] + b"\x00\x00\x00\x00")
    hash_raw = blake3(h80_raw)
    res = hoohash_v110(seed_raw, hash_raw, nonce_val_raw).hex()
    if int(res, 16) <= int(target, 16):
        print(f"!!! HIT (raw_header) !!! Result:{res}")
    
    # Hypothesis: Input hash is based on coinbase hash
    cb_hash_hex = record.get("coinbaseHashLocal")
    if cb_hash_hex:
        cb_hash = bytes.fromhex(cb_hash_hex)
        for s_name, seed in seeds:
            res = hoohash_v110(seed, cb_hash, nonce_le).hex()
            if int(res, 16) <= int(target, 16):
                print(f"!!! HIT (cb_hash) !!! Seed:{s_name} Result:{res}")

    print("-" * 20)

if __name__ == "__main__":
    evidence_file = Path("/home/ubuntu/pool-pepepow/.runtime/live-stratum/submit-evidence.jsonl")
    if not evidence_file.exists():
        print("Evidence file not found")
        sys.exit(1)
        
    with open(evidence_file, "r") as f:
        lines = f.readlines()
        for line in lines[-5:]:
            run_probe(json.loads(line))
