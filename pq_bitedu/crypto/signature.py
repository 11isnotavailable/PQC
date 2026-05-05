"""Signature scheme abstractions and implementations."""

from __future__ import annotations

import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ..serialization import canonical_json_bytes, decode_signature_json
from .hashing import sha256


@dataclass
class KeyPair:
    public_key: bytes
    private_key: Any


class SignatureScheme(ABC):
    """A stateful or stateless signature backend."""

    name = "abstract"

    @abstractmethod
    def keygen(self) -> KeyPair:
        raise NotImplementedError

    @abstractmethod
    def sign(self, private_key: Any, message: bytes) -> bytes:
        raise NotImplementedError

    @abstractmethod
    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        raise NotImplementedError

    def estimate_public_key_size(self, public_key: bytes) -> int:
        return len(public_key)

    def estimate_signature_size(self, signature: bytes) -> int:
        return len(signature)


@dataclass(frozen=True)
class EducationalMLDSAParams:
    """Small module-lattice parameters for a teaching-oriented ML-DSA style scheme."""

    n: int = 32
    q: int = 12289
    k: int = 3
    l: int = 3
    eta: int = 2
    gamma1: int = 64
    tau: int = 8


@dataclass(frozen=True)
class SparseChallenge:
    positions: Tuple[int, ...]
    signs: Tuple[int, ...]
    polynomial: Tuple[int, ...]


class EducationalMLDSASignature(SignatureScheme):
    """
    Handwritten ML-DSA-inspired signature backend.

    This is intentionally not a byte-for-byte FIPS 204 implementation. Instead it
    keeps the core module-lattice signing logic: public matrix expansion,
    short secret vectors, a Fiat-Shamir sparse challenge, and bounded signature
    vectors. That makes the project self-contained and explainable in class while
    still being much closer to ML-DSA logic than a hash-based fallback.
    """

    name = "ml-dsa-44"
    implementation_name = "handwritten-edu"

    def __init__(self, params: Optional[EducationalMLDSAParams] = None) -> None:
        self.params = params or EducationalMLDSAParams()
        self._z_bound = self.params.gamma1 + self.params.tau * self.params.eta

    def keygen(self) -> KeyPair:
        rho = secrets.token_bytes(32)
        secret_seed = secrets.token_bytes(32)
        nonce_seed = secrets.token_bytes(32)
        matrix = self._expand_matrix(rho)
        short_secret = self._expand_small_vector(secret_seed + b"|s", self.params.l, self.params.eta)
        public_vector = self._matrix_vector_mul(matrix, short_secret)
        public_key = canonical_json_bytes(
            {
                "scheme": self.name,
                "implementation": self.implementation_name,
                "params": self._params_dict(),
                "rho": rho.hex(),
                "t": public_vector,
            }
        )
        private_key = {
            "scheme": self.name,
            "implementation": self.implementation_name,
            "params": self._params_dict(),
            "rho": rho,
            "s": short_secret,
            "t": public_vector,
            "nonce_seed": nonce_seed,
            "public_key": public_key,
        }
        return KeyPair(public_key=public_key, private_key=private_key)

    def sign(self, private_key: Any, message: bytes) -> bytes:
        if private_key.get("scheme") != self.name:
            raise RuntimeError("private key does not belong to the educational ML-DSA backend")
        matrix = self._expand_matrix(private_key["rho"])
        mu = sha256(private_key["public_key"] + b"|" + message)
        nonce_seed = sha256(private_key["nonce_seed"] + mu)

        for counter in range(256):
            counter_bytes = counter.to_bytes(2, "little")
            ephemeral = self._expand_bounded_vector(
                nonce_seed + b"|y|" + counter_bytes,
                self.params.l,
                self.params.gamma1,
            )
            witness = self._matrix_vector_mul(matrix, ephemeral)
            challenge = self._sample_challenge(mu, witness)
            correction = [
                self._poly_mul_small(challenge.polynomial, secret_poly)
                for secret_poly in private_key["s"]
            ]
            z_vector = [
                self._poly_add_centered(ephemeral_poly, correction_poly)
                for ephemeral_poly, correction_poly in zip(ephemeral, correction)
            ]
            if self._max_abs_vector(z_vector) > self._z_bound:
                continue
            return canonical_json_bytes(
                {
                    "scheme": self.name,
                    "implementation": self.implementation_name,
                    "z": z_vector,
                    "challenge_positions": challenge.positions,
                    "challenge_signs": challenge.signs,
                }
            )
        raise RuntimeError("failed to produce bounded signature after 256 attempts")

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        try:
            parsed_public_key = decode_signature_json(public_key)
            parsed_signature = decode_signature_json(signature)
        except Exception:
            return False

        if parsed_public_key.get("scheme") != self.name:
            return False
        if parsed_signature.get("scheme") != self.name:
            return False

        try:
            rho = bytes.fromhex(parsed_public_key["rho"])
            public_vector = [self._reduce_poly(poly) for poly in parsed_public_key["t"]]
            z_vector = [self._decode_centered_poly(poly) for poly in parsed_signature["z"]]
            positions = tuple(int(index) for index in parsed_signature["challenge_positions"])
            signs = tuple(int(sign) for sign in parsed_signature["challenge_signs"])
        except Exception:
            return False

        if len(public_vector) != self.params.k or len(z_vector) != self.params.l:
            return False
        if len(positions) != self.params.tau or len(signs) != self.params.tau:
            return False
        if self._max_abs_vector(z_vector) > self._z_bound:
            return False

        challenge = self._challenge_from_sparse(positions, signs)
        if challenge is None:
            return False

        matrix = self._expand_matrix(rho)
        az_vector = self._matrix_vector_mul(matrix, z_vector)
        ct_vector = [
            self._poly_mul_mod_q(challenge.polynomial, public_poly)
            for public_poly in public_vector
        ]
        reconstructed_witness = [
            self._poly_sub_mod_q(left_poly, right_poly)
            for left_poly, right_poly in zip(az_vector, ct_vector)
        ]
        mu = sha256(public_key + b"|" + message)
        expected_challenge = self._sample_challenge(mu, reconstructed_witness)
        return (
            positions == expected_challenge.positions
            and signs == expected_challenge.signs
        )

    def _params_dict(self) -> Dict[str, int]:
        return {
            "n": self.params.n,
            "q": self.params.q,
            "k": self.params.k,
            "l": self.params.l,
            "eta": self.params.eta,
            "gamma1": self.params.gamma1,
            "tau": self.params.tau,
        }

    def _expand_matrix(self, seed: bytes) -> List[List[List[int]]]:
        matrix: List[List[List[int]]] = []
        for row in range(self.params.k):
            row_polys: List[List[int]] = []
            for column in range(self.params.l):
                label = b"A|" + bytes([row, column])
                row_polys.append(self._expand_uniform_poly(seed + label))
            matrix.append(row_polys)
        return matrix

    def _expand_uniform_poly(self, seed: bytes) -> List[int]:
        stream = hashlib.shake_256(seed).digest(self.params.n * 2)
        coefficients = []
        for index in range(self.params.n):
            chunk = stream[index * 2 : index * 2 + 2]
            coefficients.append(int.from_bytes(chunk, "little") % self.params.q)
        return coefficients

    def _expand_small_vector(self, seed: bytes, count: int, bound: int) -> List[List[int]]:
        modulus = 2 * bound + 1
        vector: List[List[int]] = []
        for index in range(count):
            stream = hashlib.shake_256(seed + b"|small|" + bytes([index])).digest(self.params.n)
            vector.append([(byte % modulus) - bound for byte in stream])
        return vector

    def _expand_bounded_vector(self, seed: bytes, count: int, bound: int) -> List[List[int]]:
        modulus = 2 * bound + 1
        vector: List[List[int]] = []
        for index in range(count):
            stream = hashlib.shake_256(seed + b"|wide|" + bytes([index])).digest(self.params.n * 2)
            coefficients = []
            for offset in range(self.params.n):
                chunk = stream[offset * 2 : offset * 2 + 2]
                coefficients.append((int.from_bytes(chunk, "little") % modulus) - bound)
            vector.append(coefficients)
        return vector

    def _sample_challenge(self, mu: bytes, witness: Sequence[Sequence[int]]) -> SparseChallenge:
        serialized = canonical_json_bytes({"mu": mu.hex(), "w": witness})
        stream = bytearray(hashlib.shake_256(serialized).digest(96))
        cursor = 0
        used_positions = set()
        positions: List[int] = []
        signs: List[int] = []
        while len(positions) < self.params.tau:
            if cursor + 3 > len(stream):
                stream.extend(hashlib.shake_256(bytes(stream)).digest(32))
            position = int.from_bytes(stream[cursor : cursor + 2], "little") % self.params.n
            cursor += 2
            if position in used_positions:
                continue
            sign = 1 if stream[cursor] & 1 == 0 else -1
            cursor += 1
            used_positions.add(position)
            positions.append(position)
            signs.append(sign)
        challenge = [0] * self.params.n
        for position, sign in zip(positions, signs):
            challenge[position] = sign
        return SparseChallenge(
            positions=tuple(positions),
            signs=tuple(signs),
            polynomial=tuple(challenge),
        )

    def _challenge_from_sparse(
        self,
        positions: Sequence[int],
        signs: Sequence[int],
    ) -> Optional[SparseChallenge]:
        if len(set(positions)) != len(positions):
            return None
        challenge = [0] * self.params.n
        for position, sign in zip(positions, signs):
            if position < 0 or position >= self.params.n:
                return None
            if sign not in (-1, 1):
                return None
            challenge[position] = sign
        return SparseChallenge(
            positions=tuple(positions),
            signs=tuple(signs),
            polynomial=tuple(challenge),
        )

    def _matrix_vector_mul(
        self,
        matrix: Sequence[Sequence[Sequence[int]]],
        vector: Sequence[Sequence[int]],
    ) -> List[List[int]]:
        if len(vector) != self.params.l:
            raise ValueError("vector length does not match matrix width")
        result: List[List[int]] = []
        for row in matrix:
            accumulator = [0] * self.params.n
            for left_poly, right_poly in zip(row, vector):
                accumulator = self._poly_add_mod_q(
                    accumulator,
                    self._poly_mul_mod_q(left_poly, right_poly),
                )
            result.append(accumulator)
        return result

    def _poly_mul_mod_q(self, left: Sequence[int], right: Sequence[int]) -> List[int]:
        raw = [0] * self.params.n
        for left_index, left_coeff in enumerate(left):
            for right_index, right_coeff in enumerate(right):
                product = int(left_coeff) * int(right_coeff)
                output_index = left_index + right_index
                if output_index >= self.params.n:
                    output_index -= self.params.n
                    raw[output_index] -= product
                else:
                    raw[output_index] += product
        return [value % self.params.q for value in raw]

    def _poly_mul_small(self, left: Sequence[int], right: Sequence[int]) -> List[int]:
        raw = [0] * self.params.n
        for left_index, left_coeff in enumerate(left):
            if left_coeff == 0:
                continue
            for right_index, right_coeff in enumerate(right):
                product = int(left_coeff) * int(right_coeff)
                output_index = left_index + right_index
                if output_index >= self.params.n:
                    output_index -= self.params.n
                    raw[output_index] -= product
                else:
                    raw[output_index] += product
        return raw

    def _poly_add_mod_q(self, left: Sequence[int], right: Sequence[int]) -> List[int]:
        return [
            (int(left_coeff) + int(right_coeff)) % self.params.q
            for left_coeff, right_coeff in zip(left, right)
        ]

    def _poly_sub_mod_q(self, left: Sequence[int], right: Sequence[int]) -> List[int]:
        return [
            (int(left_coeff) - int(right_coeff)) % self.params.q
            for left_coeff, right_coeff in zip(left, right)
        ]

    @staticmethod
    def _poly_add_centered(left: Sequence[int], right: Sequence[int]) -> List[int]:
        return [int(left_coeff) + int(right_coeff) for left_coeff, right_coeff in zip(left, right)]

    def _reduce_poly(self, coefficients: Sequence[int]) -> List[int]:
        if len(coefficients) != self.params.n:
            raise ValueError("unexpected polynomial length")
        return [int(coefficient) % self.params.q for coefficient in coefficients]

    def _decode_centered_poly(self, coefficients: Sequence[int]) -> List[int]:
        if len(coefficients) != self.params.n:
            raise ValueError("unexpected polynomial length")
        return [int(coefficient) for coefficient in coefficients]

    @staticmethod
    def _max_abs_vector(vector: Sequence[Sequence[int]]) -> int:
        maximum = 0
        for poly in vector:
            for coefficient in poly:
                maximum = max(maximum, abs(int(coefficient)))
        return maximum


MLDSASignature = EducationalMLDSASignature


class MerkleLamportSignature(SignatureScheme):
    """
    Educational many-time hash-based signature scheme.

    This is the offline fallback backend when ML-DSA is unavailable. It remains
    post-quantum in spirit because it relies on hash preimage resistance, while
    still being small enough to implement locally for coursework.
    """

    name = "merkle-lamport"

    def __init__(self, leaf_count: int = 32, pair_count: int = 128, digest_size: int = 32) -> None:
        if leaf_count <= 0 or leaf_count & (leaf_count - 1):
            raise ValueError("leaf_count must be a positive power of two")
        if pair_count % 8 != 0:
            raise ValueError("pair_count must be divisible by 8")
        self.leaf_count = leaf_count
        self.pair_count = pair_count
        self.digest_size = digest_size

    def keygen(self) -> KeyPair:
        secret_pairs: List[List[Tuple[bytes, bytes]]] = []
        public_pairs: List[List[Tuple[bytes, bytes]]] = []

        for _ in range(self.leaf_count):
            leaf_secret_pairs: List[Tuple[bytes, bytes]] = []
            leaf_public_pairs: List[Tuple[bytes, bytes]] = []
            for _pair_index in range(self.pair_count):
                left_secret = secrets.token_bytes(self.digest_size)
                right_secret = secrets.token_bytes(self.digest_size)
                leaf_secret_pairs.append((left_secret, right_secret))
                leaf_public_pairs.append((sha256(left_secret), sha256(right_secret)))
            secret_pairs.append(leaf_secret_pairs)
            public_pairs.append(leaf_public_pairs)

        leaves = [sha256(self._serialize_ots_public_key(leaf_pairs)) for leaf_pairs in public_pairs]
        tree_levels = self._build_merkle_tree(leaves)
        root = tree_levels[-1][0]

        public_key = canonical_json_bytes(
            {
                "scheme": self.name,
                "leaf_count": self.leaf_count,
                "pair_count": self.pair_count,
                "digest_size": self.digest_size,
                "root": root.hex(),
            }
        )
        private_key: Dict[str, Any] = {
            "scheme": self.name,
            "leaf_count": self.leaf_count,
            "pair_count": self.pair_count,
            "digest_size": self.digest_size,
            "root": root,
            "tree_levels": tree_levels,
            "secret_pairs": secret_pairs,
            "public_pairs": public_pairs,
            "next_index": 0,
        }
        return KeyPair(public_key=public_key, private_key=private_key)

    def sign(self, private_key: Any, message: bytes) -> bytes:
        if private_key["next_index"] >= private_key["leaf_count"]:
            raise RuntimeError("Merkle-Lamport private key exhausted")

        index = private_key["next_index"]
        private_key["next_index"] += 1
        bits = self._message_bits(message)
        leaf_secret_pairs = private_key["secret_pairs"][index]
        leaf_public_pairs = private_key["public_pairs"][index]
        revealed = [leaf_secret_pairs[pair_index][bit] for pair_index, bit in enumerate(bits)]
        auth_path = self._auth_path(private_key["tree_levels"], index)

        return canonical_json_bytes(
            {
                "scheme": self.name,
                "index": index,
                "revealed": [piece.hex() for piece in revealed],
                "ots_public_key": [
                    [left.hex(), right.hex()] for left, right in leaf_public_pairs
                ],
                "auth_path": [item.hex() for item in auth_path],
            }
        )

    def verify(self, public_key: bytes, message: bytes, signature: bytes) -> bool:
        try:
            parsed_public_key = decode_signature_json(public_key)
            parsed_signature = decode_signature_json(signature)
        except Exception:
            return False

        if parsed_public_key.get("scheme") != self.name:
            return False
        if parsed_signature.get("scheme") != self.name:
            return False

        index = int(parsed_signature["index"])
        if index < 0 or index >= int(parsed_public_key["leaf_count"]):
            return False

        digest_bits = self._message_bits(message)
        revealed = [bytes.fromhex(part) for part in parsed_signature["revealed"]]
        if len(revealed) != self.pair_count:
            return False

        try:
            ots_public_key = [
                (bytes.fromhex(left_hex), bytes.fromhex(right_hex))
                for left_hex, right_hex in parsed_signature["ots_public_key"]
            ]
        except Exception:
            return False

        if len(ots_public_key) != self.pair_count:
            return False

        for pair_index, bit in enumerate(digest_bits):
            expected_hash = ots_public_key[pair_index][bit]
            if sha256(revealed[pair_index]) != expected_hash:
                return False

        try:
            auth_path = [bytes.fromhex(item) for item in parsed_signature["auth_path"]]
        except Exception:
            return False

        leaf_hash = sha256(self._serialize_ots_public_key(ots_public_key))
        root = self._root_from_auth_path(leaf_hash, index, auth_path)
        return root.hex() == parsed_public_key["root"]

    def _message_bits(self, message: bytes) -> List[int]:
        byte_length = self.pair_count // 8
        digest = sha256(message)[:byte_length]
        bits: List[int] = []
        for byte in digest:
            for shift in range(7, -1, -1):
                bits.append((byte >> shift) & 1)
        return bits[: self.pair_count]

    @staticmethod
    def _serialize_ots_public_key(public_pairs: Sequence[Tuple[bytes, bytes]]) -> bytes:
        return b"".join(left + right for left, right in public_pairs)

    @staticmethod
    def _build_merkle_tree(leaves: Sequence[bytes]) -> List[List[bytes]]:
        levels = [list(leaves)]
        current = list(leaves)
        while len(current) > 1:
            next_level: List[bytes] = []
            for index in range(0, len(current), 2):
                next_level.append(sha256(current[index] + current[index + 1]))
            levels.append(next_level)
            current = next_level
        return levels

    @staticmethod
    def _auth_path(tree_levels: Sequence[Sequence[bytes]], index: int) -> List[bytes]:
        path: List[bytes] = []
        current_index = index
        for level in tree_levels[:-1]:
            sibling_index = current_index ^ 1
            path.append(level[sibling_index])
            current_index //= 2
        return path

    @staticmethod
    def _root_from_auth_path(leaf_hash: bytes, index: int, auth_path: Sequence[bytes]) -> bytes:
        node = leaf_hash
        current_index = index
        for sibling in auth_path:
            if current_index % 2 == 0:
                node = sha256(node + sibling)
            else:
                node = sha256(sibling + node)
            current_index //= 2
        return node


def build_signature_schemes() -> Dict[str, SignatureScheme]:
    primary: SignatureScheme = EducationalMLDSASignature()
    schemes: Dict[str, SignatureScheme] = {primary.name: primary}
    fallback = MerkleLamportSignature()
    if fallback.name not in schemes:
        schemes[fallback.name] = fallback
    return schemes


def default_scheme_name(signature_schemes: Mapping[str, SignatureScheme]) -> str:
    if EducationalMLDSASignature.name in signature_schemes:
        return EducationalMLDSASignature.name
    if not signature_schemes:
        raise ValueError("at least one signature scheme is required")
    return next(iter(signature_schemes))
