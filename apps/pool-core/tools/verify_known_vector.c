#include <stdio.h>
#include <stdint.h>
#include <string.h>

extern int pepepow_blake3_hash(const uint8_t *input, size_t len, uint8_t output[32]);
extern void generateHoohashMatrixV110(const uint8_t seed[32], double out[64][64]);
extern void HoohashMatrixMultiplication(double mat[64][64], const uint8_t *hashBytes, uint8_t *output, uint64_t nonce);

int main() {
    // Known vector from tests/test_stratum_ingress.py
    const char *header_hex = "0040002038e31388c54124146478ff691985eecd02610db91efbc9cd7aabca490000000007647f0508057dbf8c99ddaa87543c04e31dfe3f383e7386903d50c91728fabe830be16971e3021da96d9d33";
    const char *expected_hash_hex = "00000001fb895a82973fca52938848908d6a6cb3c0dfb93995dc61020ced0a6b";
    
    uint8_t header[80];
    for (int i=0; i<80; i++) sscanf(header_hex + 2*i, "%2hhx", &header[i]);
    
    uint8_t seed_input[80];
    memcpy(seed_input, header, 76);
    memset(seed_input + 76, 0, 4);
    
    uint8_t matrix_seed[32];
    pepepow_blake3_hash(seed_input, 80, matrix_seed);
    
    uint8_t header_hash[32];
    pepepow_blake3_hash(header, 80, header_hash);
    
    uint32_t nonce;
    memcpy(&nonce, header + 76, 4); // Little-endian read
    
    double mat[64][64];
    generateHoohashMatrixV110(matrix_seed, mat);
    
    uint8_t output[32];
    HoohashMatrixMultiplication(mat, header_hash, output, (uint64_t)nonce);
    
    printf("Computed: ");
    for(int i=0; i<32; i++) printf("%02x", output[i]);
    printf("\nExpected: %s\n", expected_hash_hex);
    
    if (memcmp(output, "\x00\x00\x00\x01\xfb\x89\x5a\x82", 8) == 0) { // Check first bytes
        printf("MATCH!\n");
    } else {
        printf("FAIL\n");
    }
    
    return 0;
}
