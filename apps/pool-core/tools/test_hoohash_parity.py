
import sys
from pathlib import Path

# Add current dir to path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from pepepow_pow import blake3_hash, hoohash_v110, hoohash_v110_direct

def test_parity():
    # Dummy 80-byte header
    header = bytes([i for i in range(80)])
    
    # 1. Direct call
    direct_res = hoohash_v110_direct(header)
    print(f"Direct: {direct_res.hex()}")
    
    # 2. Reconstructed split path
    masked_header = header[:76] + b"\x00\x00\x00\x00"
    matrix_seed = blake3_hash(masked_header)
    header_hash = blake3_hash(header)
    nonce = int.from_bytes(header[76:80], byteorder="little")
    
    split_res = hoohash_v110(matrix_seed, header_hash, nonce)
    print(f"Split:  {split_res.hex()}")
    
    # 3. Reversed split path
    reversed_split = split_res[::-1]
    print(f"RevSplit: {reversed_split.hex()}")
    
    if direct_res == reversed_split:
        print("SUCCESS: Direct path matches reversed split path.")
    else:
        print("FAILURE: Mismatch!")
        sys.exit(1)

if __name__ == "__main__":
    test_parity()
