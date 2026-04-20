import sys
from pathlib import Path

# Add apps/pool-core to sys.path
sys.path.append(str(Path("/home/ubuntu/pool-pepepow/apps/pool-core")))

from pepepow_pow import hoohash_v110, hoohash_v110_direct, blake3_hash

def test_consistency():
    # Header from log entry
    header_hex = "004000207ebad826060466419977a99027eb767e6f90db721486f3b3cbd90ac100000000790559ca5a774845b0e83f51ca933305e3354f473538978f2267e8d5203611ba3211e6691197011d415da657"
    header = bytes.fromhex(header_hex)
    
    # Calculate direct (authoritative)
    direct_hash = hoohash_v110_direct(header)
    print(f"Direct Hash: {direct_hash.hex()}")
    
    # Calculate via matrix (pool's path)
    masked_header = header[:76] + b"\x00\x00\x00\x00"
    header_hash = blake3_hash(header)
    matrix_seed = blake3_hash(masked_header)
    # Correct nonce extraction from header (bytes 76-80)
    import struct
    nonce = struct.unpack("<I", header[76:80])[0]
    
    matrix_hash = hoohash_v110(matrix_seed, header_hash, nonce)
    print(f"Matrix Hash: {matrix_hash.hex()}")
    
    if direct_hash == matrix_hash:
        print("SUCCESS: Hashes match!")
    else:
        print("FAILURE: Hashes mismatch!")
        if direct_hash == matrix_hash[::-1]:
            print("REASON detected: Bytes are REVERSED!")
        else:
            print("REASON: Unknown mismatch.")

if __name__ == "__main__":
    test_consistency()
