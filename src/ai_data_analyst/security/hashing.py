"""Stable hashing helpers for audit subjects.

A hash of a low-entropy value (short SQL with literals, a small parameter set) can be
guessed by brute force. It proves identity, not anonymization.
"""

from __future__ import annotations

import hashlib
import json


def hash_text(text: str) -> str:
    """Return the lowercase SHA-256 hex digest of *text* encoded as UTF-8.

    Use this for normalized SQL. A hash of a low-entropy value can be guessed by brute
    force: it proves identity, not anonymization.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def hash_canonical_json(value: object) -> str:
    """Hash a JSON value after canonical serialization.

    The encoding uses sorted keys, compact separators, ASCII escapes and rejects NaN and
    infinity. Tuples serialize like lists. A hash of a low-entropy value can be guessed by
    brute force: it proves identity, not anonymization.
    """
    try:
        canonical = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("value must be JSON-serializable and contain only finite numbers") from exc
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
