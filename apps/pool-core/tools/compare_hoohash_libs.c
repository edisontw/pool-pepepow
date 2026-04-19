#include <stdio.h>
#include <stdint.h>
#include <string.h>
#include <math.h>

extern void generateHoohashMatrixV110(const uint8_t seed[32], double out[64][64]);
extern void HoohashMatrixMultiplication(double mat[64][64], const uint8_t *hashBytes, uint8_t *output, uint64_t nonce);

// Local implementation from pepepow_pow_helper.c for comparison
typedef struct {
    uint64_t s0, s1, s2, s3;
} xo_shi_ro_256_pp;

static inline uint64_t rotl(const uint64_t x, int k) {
    return (x << k) | (x >> (64 - k));
}

static uint64_t xo_shi_ro_next(xo_shi_ro_256_pp *state) {
    const uint64_t result = rotl(state->s0 + state->s3, 23) + state->s0;
    const uint64_t t = state->s1 << 17;
    state->s2 ^= state->s0;
    state->s3 ^= state->s1;
    state->s1 ^= state->s2;
    state->s0 ^= state->s3;
    state->s2 ^= t;
    state->s3 = rotl(state->s3, 45);
    return result;
}

static void xo_shi_ro_init(xo_shi_ro_256_pp *state, const uint8_t seed[32]) {
    memcpy(&state->s0, seed + 0, 8);
    memcpy(&state->s1, seed + 8, 8);
    memcpy(&state->s2, seed + 16, 8);
    memcpy(&state->s3, seed + 24, 8);
}

void local_generate_matrix(const uint8_t seed[32], double out[64][64], double normalize) {
    xo_shi_ro_256_pp gen;
    xo_shi_ro_init(&gen, seed);
    for (int i = 0; i < 64; i++) {
        for (int j = 0; j < 64; j++) {
            uint64_t val = xo_shi_ro_next(&gen);
            out[i][j] = ((double)(uint32_t)val / (double)0xFFFFFFFFu) * normalize;
        }
    }
}

int main() {
    uint8_t seed[32] = {0};
    seed[0] = 1; // Simple seed
    
    double mat_lib[64][64];
    double mat_local[64][64];
    
    generateHoohashMatrixV110(seed, mat_lib);
    
    // Try to find matching normalize
    double test_values[] = {1.0, 1000000.0, 4294967295.0, 2.0};
    for (int t = 0; t < 4; t++) {
        local_generate_matrix(seed, mat_local, test_values[t]);
        double diff = 0;
        for (int i=0; i<64; i++) for (int j=0; j<64; j++) diff += fabs(mat_lib[i][j] - mat_local[i][j]);
        printf("Normalize %f -> Diff %f\n", test_values[t], diff);
    }
    
    printf("First few elements of Lib matrix:\n");
    for(int i=0; i<4; i++) printf("%f ", mat_lib[0][i]);
    printf("\n");
    
    return 0;
}
