from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path


APP_DIR = Path(__file__).resolve().parent
RUNTIME_BUILD_DIR = APP_DIR.parent.parent / ".runtime" / "pool-core-build"
LIB_PATH = RUNTIME_BUILD_DIR / "libpepepow_pow.so"
HELPER_SOURCE = APP_DIR / "pepepow_pow_helper.c"
BLAKE3_HEADER = APP_DIR / "blake3.h"
LIB_DIR = APP_DIR / "libs" / "aarch64-linux"
LIB_HOOHASH = LIB_DIR / "libhoohash.a"
LIB_BLAKE3 = LIB_DIR / "libblake3.a"

# Host-local authority:
# - installed PEPEPOWd/PEPEPOW-cli v2.9.0.4-c1394e6
# - local RPC-observed chain behavior
#
# This bridge exists because PEPEPOWd is a stripped executable, not a stable
# library ABI we can link against. The vendored static libraries keep runtime
# hashing independent from any /tmp exploration checkout.


class PepepowPowError(RuntimeError):
    pass


class _PepepowPowLibrary:
    def __init__(self) -> None:
        self._lib = self._load()
        self._configure()

    def _load(self) -> ctypes.CDLL:
        _ensure_library()
        return ctypes.CDLL(str(LIB_PATH))

    def _configure(self) -> None:
        self._lib.pepepow_blake3_hash.argtypes = [
            ctypes.c_void_p,
            ctypes.c_size_t,
            ctypes.c_void_p,
        ]
        self._lib.pepepow_blake3_hash.restype = ctypes.c_int
        self._lib.pepepow_hoohash_v110.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_void_p,
        ]
        self._lib.pepepow_hoohash_v110.restype = ctypes.c_int
        self._lib.pepepow_hoohash_variant.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
            ctypes.c_uint64,
            ctypes.c_int,
            ctypes.c_void_p,
        ]
        self._lib.pepepow_hoohash_variant.restype = ctypes.c_int
        self._lib.pepepow_hoohash_v110_direct.argtypes = [
            ctypes.c_void_p,
            ctypes.c_void_p,
        ]
        self._lib.pepepow_hoohash_v110_direct.restype = ctypes.c_int

    def blake3_hash(self, payload: bytes) -> bytes:
        return _call_bytes3(self._lib.pepepow_blake3_hash, payload)

    def hoohash_v110(self, seed: bytes, input_hash: bytes, nonce: int) -> bytes:
        return _call_pow(self._lib.pepepow_hoohash_v110, seed, input_hash, nonce)

    def hoohash_variant(self, seed: bytes, input_hash: bytes, nonce: int, variant: int) -> bytes:
        return _call_pow_variant(self._lib.pepepow_hoohash_variant, seed, input_hash, nonce, variant)

    def hoohash_v110_direct(self, header: bytes) -> bytes:
        if len(header) != 80:
            raise PepepowPowError(f"PEPEPOW header must be 80 bytes, got {len(header)}")
        output = ctypes.create_string_buffer(32)
        header_buffer = ctypes.create_string_buffer(header, 80)
        rc = self._lib.pepepow_hoohash_v110_direct(header_buffer, output)
        if rc != 0:
            raise PepepowPowError(f"native helper returned {rc}")
        return output.raw


def _call_bytes3(func: ctypes._CFuncPtr, payload: bytes) -> bytes:
    output = ctypes.create_string_buffer(32)
    buffer = ctypes.create_string_buffer(payload, len(payload))
    rc = func(buffer, len(payload), output)
    if rc != 0:
        raise PepepowPowError(f"native helper returned {rc}")
    return output.raw


def _call_pow(
    func: ctypes._CFuncPtr,
    seed: bytes,
    input_hash: bytes,
    nonce: int,
) -> bytes:
    if len(seed) != 32 or len(input_hash) != 32:
        raise PepepowPowError("seed and input hash must be 32 bytes")
    output = ctypes.create_string_buffer(32)
    seed_buffer = ctypes.create_string_buffer(seed, 32)
    input_buffer = ctypes.create_string_buffer(input_hash, 32)
    rc = func(seed_buffer, input_buffer, nonce, output)
    if rc != 0:
        raise PepepowPowError(f"native helper returned {rc}")
    return output.raw
def _call_pow_variant(
    func: ctypes._CFuncPtr,
    seed: bytes,
    input_hash: bytes,
    nonce: int,
    variant: int,
) -> bytes:
    if len(seed) != 32 or len(input_hash) != 32:
        raise PepepowPowError("seed and input hash must be 32 bytes")
    output = ctypes.create_string_buffer(32)
    seed_buffer = ctypes.create_string_buffer(seed, 32)
    input_buffer = ctypes.create_string_buffer(input_hash, 32)
    rc = func(seed_buffer, input_buffer, nonce, variant, output)
    if rc != 0:
        raise PepepowPowError(f"native helper returned {rc}")
    return output.raw


_LIBRARY: _PepepowPowLibrary | None = None


def blake3_hash(payload: bytes) -> bytes:
    return _get_library().blake3_hash(payload)


def hoohash_v110(seed: bytes, input_hash: bytes, nonce: int) -> bytes:
    return _get_library().hoohash_v110(seed, input_hash, nonce)


def hoohash_variant(seed: bytes, input_hash: bytes, nonce: int, variant: int) -> bytes:
    return _get_library().hoohash_variant(seed, input_hash, nonce, variant)


def hoohash_v110_direct(header: bytes) -> bytes:
    return _get_library().hoohash_v110_direct(header)


def _get_library() -> _PepepowPowLibrary:
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _PepepowPowLibrary()
    return _LIBRARY


def _ensure_library() -> None:
    RUNTIME_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    if not BLAKE3_HEADER.exists():
        raise PepepowPowError("required blake3.h header is missing")
    if not LIB_HOOHASH.exists() or not LIB_BLAKE3.exists():
        raise PepepowPowError("required Hoohash/Blake3 static libraries are missing")
    needs_rebuild = (
        not LIB_PATH.exists()
        or LIB_PATH.stat().st_mtime < HELPER_SOURCE.stat().st_mtime
        or LIB_PATH.stat().st_mtime < BLAKE3_HEADER.stat().st_mtime
        or LIB_PATH.stat().st_mtime < LIB_HOOHASH.stat().st_mtime
        or LIB_PATH.stat().st_mtime < LIB_BLAKE3.stat().st_mtime
    )
    if not needs_rebuild:
        return
    subprocess.run(
        [
            "gcc",
            "-shared",
            "-fPIC",
            "-O2",
            "-std=c11",
            "-I",
            str(APP_DIR),
            str(HELPER_SOURCE),
            str(APP_DIR / "hoohash.c"),
            str(LIB_HOOHASH),
            str(LIB_BLAKE3),
            "-o",
            str(LIB_PATH),
            "-lm",
        ],
        check=True,
        cwd=str(RUNTIME_BUILD_DIR),
    )
