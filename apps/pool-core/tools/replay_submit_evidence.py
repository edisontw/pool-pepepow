#!/usr/bin/env python3
import json
import sys
import argparse
from pathlib import Path
from typing import Any

# Add the parent directory to sys.path to import from pool-core
sys.path.append(str(Path(__file__).resolve().parent.parent))

try:
    from pepepow_pow import blake3_hash, hoohash_v110, hoohash_variant
except ImportError:
    print("Error: Could not import pepepow_pow. Ensure this tool is run from the pool repo.")
    sys.exit(1)

def get_seed(header80: bytes, mask_start: int) -> bytes:
    masked = header80[:mask_start] + (b"\x00" * (80 - mask_start))
    return blake3_hash(masked)

def compare_hashes(h1: str, h2: str) -> str:
    if h1.lower() == h2.lower():
        return "MATCH"
    return "MISMATCH"

def format_target_diff(hash_hex: str, target_hex: str) -> str:
    h_val = int(hash_hex, 16)
    t_val = int(target_hex, 16)
    if h_val <= t_val:
        return "!!! MEETS TARGET !!!"
    return f"ABOVE TARGET (diff: {h_val - t_val:064x})"

def get_variants(header80: bytes):
    # Base fields
    h_rev_merkle = bytearray(header80)
    h_rev_merkle[36:68] = h_rev_merkle[36:68][::-1]
    
    h_rev_ntime = bytearray(header80)
    h_rev_ntime[68:72] = h_rev_ntime[68:72][::-1]
    
    h_rev_bits = bytearray(header80)
    h_rev_bits[72:76] = h_rev_bits[72:76][::-1]

    # Nonce variants
    nonce_le = int.from_bytes(header80[76:80], "little")
    nonce_be = int.from_bytes(header80[76:80], "big")

    yield "canonical", header80, 76, nonce_le, 80
    yield "seed_full", header80, 80, nonce_le, 80
    yield "nonce_be",  header80, 76, nonce_be, 80
    yield "rev_merkle", bytes(h_rev_merkle), 76, nonce_le, 80
    yield "rev_ntime",  bytes(h_rev_ntime),  76, nonce_le, 80
    yield "rev_bits",   bytes(h_rev_bits),   76, nonce_le, 80
    yield "all_masked_76", header80, 76, nonce_le, 76
    yield "seed_mask_12", header80, 68, nonce_le, 80

def replay_evidence(record: dict[str, Any], scan=False):
    header80_hex = record.get("header80Hex")
    if not header80_hex: return
    
    header80 = bytes.fromhex(header80_hex)
    authoritative_hash = record.get("independentAuthoritativeShareHash") or record.get("localComputedHash")
    share_target_hex = record.get("shareTarget")
    
    print(f"--- Job {record.get('jobId')} | {record.get('timestamp')} ---")
    if not scan:
        print(f"Nonce (from record): {record.get('nonce')}")
        print(f"Authoritative Hash: {authoritative_hash}")
        print(f"Share Target:       {share_target_hex}")
        print("-" * 40)

    any_hit = False
    for name, h80, s_mask, nonce, h_mask in get_variants(header80):
        seed = get_seed(h80, s_mask)
        h_hash = blake3_hash(h80[:h_mask] + (b"\x00" * (80 - h_mask)))
        
        final_hash_bytes = hoohash_v110(seed, h_hash, nonce)
        final_hash = final_hash_bytes.hex()
        
        match_status = compare_hashes(final_hash, authoritative_hash)
        target_status = format_target_diff(final_hash, share_target_hex)
        
        if "!!!" in target_status or (match_status == "MATCH" and not scan):
            print(f"  Hypothesis: {name}")
            print(f"    Hash:   {final_hash}")
            print(f"    Status: {match_status} | {target_status}")
            
            # For canonical path, also compare matrix variants
            if name == "canonical":
                for v_name, v_id in [("local-v110", 0), ("lib-generic", 1), ("lib-v110", 2)]:
                    v_hash_bytes = hoohash_variant(seed, h_hash, nonce, v_id)
                    v_hash = v_hash_bytes.hex()
                    v_status = compare_hashes(v_hash, authoritative_hash)
                    v_target = format_target_diff(v_hash, share_target_hex)
                    print(f"      Matrix {v_name:12}: {v_hash} | {v_status} | {v_target}")
            
            any_hit = True
    
    if scan and not any_hit:
        # Minimal output for scan if no hits
        pass
    elif not scan:
        print()

def main():
    parser = argparse.ArgumentParser(description="Replay submit evidence with different PoW hypotheses")
    parser.add_argument("input", help="Path to submit-evidence.jsonl")
    parser.add_argument("--latest", type=int, help="Number of latest records to process (default: 1)", default=1)
    parser.add_argument("--scan", action="store_true", help="Only output successful hits")
    
    args = parser.parse_args()
    
    with open(args.input, "r") as f:
        lines = [line for line in f.readlines() if line.strip()]
        for line in lines[-args.latest:]:
            replay_evidence(json.loads(line), scan=args.scan)

if __name__ == "__main__":
    main()
