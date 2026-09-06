"""Workspace tokens. The entire access control model. See decision D7.

There are no accounts. A workspace is created anonymously, is handed a bearer token once,
and that token is the only thing that grants access. The frontend stores it and encodes it
in a shareable link, which means **anyone with the link has full access**. That is an
accepted risk of decision D7, and the interface states it plainly rather than leaving the
user to discover it.

Given the token is the only credential, two things follow.

Only its SHA-256 hash is stored. A leaked database dump therefore does not hand over every
workspace. This costs nothing, because the token is never displayed after creation and so
never needs recovering.

Comparison is constant time, and a wrong token is indistinguishable from a nonexistent
workspace. Both return the same 401. Distinguishing them would let anyone enumerate valid
workspace identifiers, and a valid identifier is most of the way to access.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

TOKEN_BYTES = 32
"""256 bits of entropy. The token is the only credential, so it is not being economised on."""


def mint_token() -> str:
    """A fresh workspace token. Returned to the client exactly once, never stored."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    """The stored form of a token: hex SHA-256.

    A plain hash rather than a password hash such as bcrypt, deliberately. Password hashes
    are slow to resist brute force against LOW entropy secrets that humans chose. This
    token is 256 random bits, so brute force is not the threat, and a slow hash on every
    single request would be a real cost for no gain.
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def tokens_match(token: str, stored_hash: str) -> bool:
    """Constant-time comparison, so response timing does not leak the hash."""
    return hmac.compare_digest(hash_token(token), stored_hash)


def parse_bearer(header_value: str | None) -> str | None:
    """Pull the token out of an ``Authorization: Bearer <token>`` header.

    Tolerant of case and extra whitespace in the scheme, because a hand-written request
    should not fail on formatting, and strict about there being exactly one token.
    """
    if not header_value:
        return None
    parts = header_value.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    token = parts[1].strip()
    return token or None
