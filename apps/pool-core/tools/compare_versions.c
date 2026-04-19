#include <stdio.h>
#include <stdint.h>
#include <string.h>

extern void generateHoohashMatrixV110(const uint8_t seed[32], double out[64][64]);
extern void HoohashMatrixMultiplication(double mat[64][64], const uint8_t *hashBytes, uint8_t *output, uint64_t nonce);
extern void CalculateProofOfWorkValueV110(const uint8_t *header, uint8_t *output);
extern void CalculateProofOfWorkValue(const uint8_t *header, uint8_t *output);

int main() {
    const char *header_hex = "0040002038e31388c54124146478ff691985eecd02610db91efbc9cd7aabca490000000007647f0508057dbf8c99ddaa87543c04e31dfe3f383e7386903d50c91728fabe830be16971e3021da96d9d33";
    
    uint8_t header[80];
    for (int i=0; i<80; i++) sscanf(header_hex + 2*i, "%2hhx", &header[i]);
    
    uint8_t output_v110[32];
    CalculateProofOfWorkValueV110(header, output_v110);
    
    uint8_t output_v100[32];
    CalculateProofOfWorkValue(header, output_v100);
    
    printf("V110: ");
    for(int i=0; i<32; i++) printf("%02x", output_v110[i]);
    printf("\n");
    
    printf("V100: ");
    for(int i=0; i<32; i++) printf("%02x", output_v100[i]);
    printf("\n");
    
    return 0;
}
