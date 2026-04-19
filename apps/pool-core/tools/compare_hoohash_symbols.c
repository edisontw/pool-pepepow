#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

extern void generateHoohashMatrix(const uint8_t seed[32], double out[64][64]);
extern void generateHoohashMatrixV110(const uint8_t seed[32], double out[64][64]);

int main() {
    uint8_t seed[32];
    for(int i=0; i<32; i++) seed[i] = i;
    
    double mat_gen[64][64];
    double mat_v110[64][64];
    
    generateHoohashMatrix(seed, mat_gen);
    generateHoohashMatrixV110(seed, mat_v110);
    
    double diff = 0;
    for(int i=0; i<64; i++) {
        for(int j=0; j<64; j++) {
            diff += fabs(mat_gen[i][j] - mat_v110[i][j]);
        }
    }
    
    printf("Difference between generateHoohashMatrix and generateHoohashMatrixV110: %f\n", diff);
    
    if (diff == 0) {
        printf("They are IDENTICAL.\n");
    } else {
        printf("They are DIFFERENT.\n");
    }
    
    return 0;
}
