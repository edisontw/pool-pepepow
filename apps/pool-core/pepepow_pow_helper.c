#include <stddef.h>
#include <stdint.h>
#include <string.h>

#include "blake3.h"

extern void HoohashMatrixMultiplication(
    double mat[64][64],
    const uint8_t *hashBytes,
    uint8_t *output,
    uint64_t nonce
);

typedef struct {
    uint64_t s0;
    uint64_t s1;
    uint64_t s2;
    uint64_t s3;
} xo_shi_ro_256_pp;

static uint64_t rotl64(uint64_t value, int shift) {
    return (value << shift) | (value >> (64 - shift));
}

static void xo_shi_ro_init(xo_shi_ro_256_pp *state, const uint8_t seed[32]) {
    memcpy(&state->s0, seed + 0, sizeof(uint64_t));
    memcpy(&state->s1, seed + 8, sizeof(uint64_t));
    memcpy(&state->s2, seed + 16, sizeof(uint64_t));
    memcpy(&state->s3, seed + 24, sizeof(uint64_t));
}

static uint64_t xo_shi_ro_next(xo_shi_ro_256_pp *state) {
    uint64_t result = rotl64(state->s0 + state->s3, 23) + state->s0;
    uint64_t t = state->s1 << 17;

    state->s2 ^= state->s0;
    state->s3 ^= state->s1;
    state->s1 ^= state->s2;
    state->s0 ^= state->s3;
    state->s2 ^= t;
    state->s3 = rotl64(state->s3, 45);
    return result;
}

static void blake3_hash(
    const uint8_t *input,
    size_t input_len,
    uint8_t output[32]
) {
    blake3_hasher hasher;
    blake3_hasher_init(&hasher);
    blake3_hasher_update(&hasher, input, input_len);
    blake3_hasher_finalize(&hasher, output, 32);
}

static void generate_hoohash_matrix_v110(
    const uint8_t seed[32],
    double out[64][64]
) {
    xo_shi_ro_256_pp generator;
    xo_shi_ro_init(&generator, seed);

    const double normalize = 1000000.0;
    for (size_t row = 0; row < 64; row++) {
        for (size_t column = 0; column < 64; column++) {
            uint64_t value = xo_shi_ro_next(&generator);
            uint32_t lower = (uint32_t)(value & 0xFFFFFFFFu);
            out[row][column] = ((double)lower / (double)UINT32_MAX) * normalize;
        }
    }
}

int pepepow_blake3_hash(
    const uint8_t *input,
    size_t input_len,
    uint8_t output[32]
) {
    blake3_hash(input, input_len, output);
    return 0;
}

extern void generateHoohashMatrix(
    const uint8_t seed[32],
    double out[64][64]
);

extern void generateHoohashMatrixV110(
    const uint8_t seed[32],
    double out[64][64]
);

int pepepow_hoohash_v110(
    const uint8_t seed[32],
    const uint8_t input_hash[32],
    uint64_t nonce,
    uint8_t output[32]
) {
    double mat[64][64];
    generate_hoohash_matrix_v110(seed, mat);
    HoohashMatrixMultiplication(mat, input_hash, output, nonce);
    return 0;
}

int pepepow_hoohash_variant(
    const uint8_t seed[32],
    const uint8_t input_hash[32],
    uint64_t nonce,
    int variant,
    uint8_t output[32]
) {
    double mat[64][64];
    // Variant mapping:
    // 0: local-v110 (default)
    // 1: lib-generic (generateHoohashMatrix)
    // 2: lib-v110 (generateHoohashMatrixV110)
    
    if (variant == 1) {
        generateHoohashMatrix(seed, mat);
    } else if (variant == 2) {
        generateHoohashMatrixV110(seed, mat);
    } else {
        generate_hoohash_matrix_v110(seed, mat);
    }
    
    HoohashMatrixMultiplication(mat, input_hash, output, nonce);
    return 0;
}
