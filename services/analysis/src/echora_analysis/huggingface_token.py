"""The Hugging Face token for gated model downloads, shared by this server and Modal.

Stored once in Settings → Analysis models, encrypted with CREDENTIAL_ENCRYPTION_KEY.
`download_models` uses it when HF_TOKEN is not set, and Modal model preparation
receives it for its downloads only. Gated models today: LTX-2.5 for motion artwork.
"""

from __future__ import annotations

import logging

import psycopg

from .settings import get_settings, require_database_url

logger = logging.getLogger(__name__)


def _cipher():
    from cryptography.fernet import Fernet

    key = get_settings().credential_encryption_key
    if not key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is required")
    return Fernet(key.encode())


def account(token: str) -> str:
    """Verify a token with Hugging Face and return its account name."""
    from huggingface_hub import HfApi

    return str(HfApi(token=token).whoami()["name"])


def stored() -> tuple[str | None, str | None]:
    """(token, account) as saved, or (None, None)."""
    with psycopg.connect(require_database_url()) as db:
        row = db.execute(
            "SELECT hf_token_encrypted, hf_token_account FROM analysis_settings WHERE singleton"
        ).fetchone()
    if not row or not row[0]:
        return None, None
    return _cipher().decrypt(bytes(row[0])).decode(), row[1]


def token_or_none() -> str | None:
    """The stored token for a download, or None when there is none or it cannot be read."""
    try:
        return stored()[0]
    except Exception as error:
        logger.warning("Could not read the stored Hugging Face token: %s", type(error).__name__)
        return None


def save(token: str | None) -> str | None:
    """Store a verified token (None or blank clears it) and return its account name."""
    token = (token or "").strip() or None
    name = account(token) if token else None
    encrypted = _cipher().encrypt(token.encode()) if token else None
    with psycopg.connect(require_database_url()) as db:
        db.execute(
            """INSERT INTO analysis_settings (singleton, hf_token_encrypted, hf_token_account, updated_at)
               VALUES (true, %s, %s, now()) ON CONFLICT (singleton) DO UPDATE
               SET hf_token_encrypted=EXCLUDED.hf_token_encrypted,
                   hf_token_account=EXCLUDED.hf_token_account, updated_at=now()""",
            (encrypted, name),
        )
    return name
