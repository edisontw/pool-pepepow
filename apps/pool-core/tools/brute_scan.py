import json
import sys
from pathlib import Path
import hashlib

# Add parent dir for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))
from pepepow_pow import hoohash_v110, blake3_hash

def dsha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()

def scan_header_permutations(record):
    print(f"Scanning permutations for record {record.get('timestamp')}")
    
    # Extract raw components (assuming they are in the order we expect from template)
    # version (8 hex), prevhash (64 hex), merkle (64 hex), ntime (8 hex), nbits (8 hex), nonce (8 hex)
    
    v = bytes.fromhex(record.get("preimageVersion"))
    p = bytes.fromhex(record.get("preimagePrevhash"))
    m = bytes.fromhex(record.get("merkleRoot"))
    t = bytes.fromhex(record.get("ntime"))
    b = bytes.fromhex(record.get("preimageNbits"))
    n = bytes.fromhex(record.get("nonce"))
    
    target = int(record.get("shareTarget"), 16)
    
    components = [v, p, m, t, b, n]
    
    for i in range(64):
        # 0: leave as is (BE), 1: reverse (LE)
        current = []
        for j in range(6):
            if (i >> j) & 1:
                current.append(components[j][::-1])
            else:
                current.append(components[j])
        
        header = b"".join(current)
        if len(header) != 80: continue
        
        # Standard hoohash v1.1.0 logic
        try:
            matrix_seed = blake3_hash(header[:76] + b"\x00"*4)
            h_hash = blake3_hash(header)
            
            # Nonce for hoohash is the value of the last 4 bytes?
            # Let's try both LE and BE interpretation of the last 4 bytes
            n_le = int.from_bytes(header[76:80], "little")
            n_be = int.from_bytes(header[76:80], "big")
            
            for n_val in [n_le, n_be]:
                res = hoohash_v110(matrix_seed, h_hash, n_val)
                hash_int = int.from_bytes(res, "big")
                if hash_int <= target:
                    flags = "".join(["L" if (i >> j) & 1 else "B" for j in range(6)])
                    print(f"!!! HIT !!! Flags:{flags} Nonce:{'LE' if n_val==n_le else 'BE'} Hash:{res.hex()}")
        except:
            pass

if __name__ == "__main__":
    path = "/home/ubuntu/pool-pepepow/.runtime/live-stratum/submit-evidence.jsonl"
    with open(path, "r") as f:
        lines = f.readlines()
        for line in lines[-5:]:
            scan_header_permutations(json.loads(line))
