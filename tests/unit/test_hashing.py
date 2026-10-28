from __future__ import annotations

import hashlib

import pytest

from ai_data_analyst.security.hashing import hash_canonical_json, hash_text


def test_hash_text_known_vectors():
    assert hash_text("") == ("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855")
    assert hash_text("abc") == ("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad")


def test_hash_text_uses_utf8():
    assert hash_text("é") == hashlib.sha256("é".encode()).hexdigest()


def test_hash_canonical_json_known_vector():
    expected = hashlib.sha256(b'{"a":1,"b":2}').hexdigest()
    assert hash_canonical_json({"b": 2, "a": 1}) == expected


def test_hash_canonical_json_is_key_order_independent():
    first = hash_canonical_json({"b": 2, "a": {"d": 4, "c": 3}})
    second = hash_canonical_json({"a": {"c": 3, "d": 4}, "b": 2})
    assert first == second


def test_hash_canonical_json_treats_tuples_like_lists():
    assert hash_canonical_json({"a": (1, 2, 3)}) == hash_canonical_json({"a": [1, 2, 3]})


def test_hash_canonical_json_escapes_non_ascii():
    expected = hashlib.sha256(b'{"\\u00e9":"\\u00e9"}').hexdigest()
    assert hash_canonical_json({"é": "é"}) == expected


def test_different_values_give_different_hashes():
    assert hash_canonical_json({"a": 1}) != hash_canonical_json({"a": 2})
    assert hash_text("a") != hash_text("b")


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        float("-inf"),
        {"nested": [1.0, float("nan")]},
    ],
)
def test_non_finite_values_are_rejected(value: object):
    with pytest.raises(ValueError, match="JSON-serializable"):
        hash_canonical_json(value)


@pytest.mark.parametrize("value", [object(), {1, 2}, b"bytes"])
def test_non_serializable_values_are_rejected(value: object):
    with pytest.raises(ValueError, match="JSON-serializable"):
        hash_canonical_json(value)
