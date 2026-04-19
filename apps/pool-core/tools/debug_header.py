import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parent.parent))

import hashlib
from pepepow_pow import hoohash_v110, blake3_hash, hoohash_variant

header_hex = "00400020ab19af833347ec84684ab3f41a87db0d50fc39f8760d014763e8f67d000000002e06e3a6021fb330d495550f0eed83af477d609c1f91756a30ef09553491e9d8dcd2e469f368021d1a706e22"
target_hex = "0000000268f30000000000000000000000000000000000000000000000000000"

header = bytes.fromhex(header_hex)
target = int(target_hex, 16)
nonce = int.from_bytes(header[76:80], byteorder="little")

print(f"Header length: {len(header)}")
print(f"Nonce (LE): {nonce}")
print(f"Target: {target_hex}")

def test_config(name, seed_bytes, header_hash_bytes):
    matrix_seed = blake3_hash(seed_bytes)
    h_hash = blake3_hash(header_hash_bytes)
    res = hoohash_v110(matrix_seed, h_hash, nonce)
    val = int.from_bytes(res, byteorder="big")
    match = val <= target
    print(f"Hypothesis {name:20}: {res.hex()} {'MATCH' if match else 'FAIL'}")
    
    # Reversal hypothesis
    res_rev = res[::-1]
    val_rev = int.from_bytes(res_rev, byteorder="big")
    match_rev = val_rev <= target
    if match_rev:
         print(f"Hypothesis {name+'_rev':20}: {res_rev.hex()} MATCH !!!")
    return match

# Original Hoohash V1.1.0 using Blake3
# We also try SHA256 variants

def test_hash_primitives(name, seed_bytes, header_hash_bytes):
    for s_algo in ["blake3", "sha256", "dsha256"]:
        for h_algo in ["blake3", "sha256", "dsha256"]:
           s_fn = lambda x: blake3_hash(x) if s_algo == "blake3" else (hashlib.sha256(x).digest() if s_algo == "sha256" else hashlib.sha256(hashlib.sha256(x).digest()).digest())
           h_fn = lambda x: blake3_hash(x) if h_algo == "blake3" else (hashlib.sha256(x).digest() if h_algo == "sha256" else hashlib.sha256(hashlib.sha256(x).digest()).digest())
           
           try:
               matrix_seed = s_fn(seed_bytes)
               h_hash = h_fn(header_hash_bytes)
               res = hoohash_v110(matrix_seed, h_hash, nonce)
               val = int.from_bytes(res, byteorder="big")
               match = val <= target
               if match:
                   print(f"!!! HIT !!! {name} S:{s_algo} H:{h_algo} Res:{res.hex()}")
           except:
               pass

test_hash_primitives("canonical_layout", header[:76] + b"\x00"*4, header)
test_hash_primitives("masked_76_both", header[:76] + b"\x00"*4, header[:76] + b"\x00"*4)

# Also try with reversed final hash
def test_hash_primitives_rev(name, seed_bytes, header_hash_bytes):
    for s_algo in ["blake3", "sha256", "dsha256"]:
        for h_algo in ["blake3", "sha256", "dsha256"]:
           s_fn = lambda x: blake3_hash(x) if s_algo == "blake3" else (hashlib.sha256(x).digest() if s_algo == "sha256" else hashlib.sha256(hashlib.sha256(x).digest()).digest())
           h_fn = lambda x: blake3_hash(x) if h_algo == "blake3" else (hashlib.sha256(x).digest() if h_algo == "sha256" else hashlib.sha256(hashlib.sha256(x).digest()).digest())
           
           try:
               matrix_seed = s_fn(seed_bytes)
               h_hash = h_fn(header_hash_bytes)
               res = hoohash_v110(matrix_seed, h_hash, nonce)[::-1]
               val = int.from_bytes(res, byteorder="big")
               match = val <= target
               if match:
                   print(f"!!! HIT REV !!! {name} S:{s_algo} H:{h_algo} Res:{res.hex()}")
           except:
               pass

test_hash_primitives_rev("canonical_layout", header[:76] + b"\x00"*4, header)

# Mask variations from conversation 9d5c4...
# "masking, seed derivation, hashing primitives"

# Legacy hoohash variant (variant 1)
def test_v1_variant(name, header_bytes):
    masked = header_bytes[:76] + b"\x00"*4
    matrix_seed = blake3_hash(masked)
    h_hash = blake3_hash(header_bytes)
    res = hoohash_variant(matrix_seed, h_hash, nonce, 1)
    val = int.from_bytes(res, byteorder="big")
    match = val <= target
    if match:
         print(f"!!! HIT V1 VARIANT !!! {name} Res:{res.hex()}")

test_v1_variant("canonical_v1", header)

def test_keccak(name, header_bytes):
    from Crypto.Hash import keccak
    def keccak256(data):
        return keccak.new(digest_bits=256, data=data).digest()
    
    try:
        matrix_seed = keccak256(header_bytes[:76] + b"\x00"*4)
        h_hash = keccak256(header_bytes)
        res = hoohash_v110(matrix_seed, h_hash, nonce)
        val = int.from_bytes(res, byteorder="big")
        match = val <= target
        if match:
             print(f"!!! HIT KECCAK !!! {name} Res:{res.hex()}")
    except:
        pass

test_keccak("canonical_keccak", header)

def test_be_seed(name, header_bytes):
    # This is hard to do without modifying the C helper or using our own matrix generator
    # But I can simulate it by reversing each 8-byte chunk of the seed!
    masked = header_bytes[:76] + b"\x00"*4
    matrix_seed = blake3_hash(masked)
    
    be_seed = bytearray()
    for i in range(0, 32, 8):
        be_seed.extend(matrix_seed[i:i+8][::-1])
    
    res = hoohash_v110(bytes(be_seed), blake3_hash(header_bytes), nonce)
    val = int.from_bytes(res, byteorder="big")
    if val <= target:
         print(f"!!! HIT BE SEED !!! {name} Res:{res.hex()}")

test_be_seed("canonical_be_seed", header)
