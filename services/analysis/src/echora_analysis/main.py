from __future__ import annotations

from collections import Counter, OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
import random
import secrets
import threading
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from urllib.parse import urlparse

import httpx
from authlib.integrations.starlette_client import OAuth, OAuthError
import igraph as ig
import numpy as np
import psycopg
from cryptography.fernet import Fernet, InvalidToken
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from sklearn.metrics import adjusted_rand_score, silhouette_score
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.orm import joinedload

from fastapi import Cookie, Depends, FastAPI, HTTPException, Request, Response
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field, HttpUrl, SecretStr
from starlette.concurrency import run_in_threadpool
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse, StreamingResponse

from .artists import fit_artist_profile, representative_indices, soft_chamfer_similarity, weighted_center
from .concepts import combine_concept_percentiles, empirical_percentiles, expand_prompts, expand_tag_groups, predefined_concepts, score_concept
from .curations import rank_curation
from .db import session_scope
from .db_models import Curation, NavidromeConnection, OidcAllowedEmail, OidcSetting, User, UserPreference, UserSession
from .hum_search import DEFAULT_CORPUS_SIZE, build_corpus, search_corpus
from .ingest import ingest_navidrome
from .journeys import normalize_rows as normalize_journey_rows, select_journey, spherical_targets
from .listening_history import recent_listens, track_listen_counts
from .karaoke_pipeline import KARAOKE_PIPELINE_REVISION, backfill_karaoke
from .melody_config import MELODY_CONTOUR_REVISION
from .lyrics_analysis import shared_lyrics_model
from .lyrics_pipeline import backfill_lyrics
from .navidrome import NavidromeClient
from .voice_pipeline import backfill_voice
from .processing_plan import plan_karaoke, plan_lyrics
from .recordings import store_and_match_fingerprint

app = FastAPI(title="Echora analysis", version="0.3.0")
app.add_middleware(
    SessionMiddleware, secret_key=os.environ.get("OIDC_SESSION_SECRET", secrets.token_urlsafe(48)),
    session_cookie="echora_oidc_state", same_site="lax",
    https_only=os.environ.get("COOKIE_SECURE", "false").lower() == "true",
)
_oauth = OAuth()
_oidc_issuer = os.environ.get("OIDC_ISSUER_URL", "").rstrip("/")
if _oidc_issuer and os.environ.get("OIDC_CLIENT_ID") and os.environ.get("OIDC_CLIENT_SECRET"):
    _oauth.register(
        name="oidc", client_id=os.environ["OIDC_CLIENT_ID"], client_secret=os.environ["OIDC_CLIENT_SECRET"],
        server_metadata_url=f"{_oidc_issuer}/.well-known/openid-configuration",
        client_kwargs={"scope": os.environ.get("OIDC_SCOPES", "openid profile email")},
    )
_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="echora-ingest")
_jobs: dict[str, dict[str, object]] = {}
_jobs_lock = threading.Lock()
_stream_cache: OrderedDict[tuple[str, str, str], tuple[bytes, str]] = OrderedDict()
_stream_cache_lock = threading.Lock()
_STREAM_CACHE_LIMIT = 12
_scheduler_started = False
_SESSION_HOURS = 2
_STREAM_CACHE_ENTRY_LIMIT = 20 * 1024 * 1024
logger = logging.getLogger(__name__)
_COMMUNITY_SNAPSHOT_REVISION = 1


class Credentials(BaseModel):
    url: HttpUrl
    username: str = Field(min_length=1)
    password: SecretStr


class DiscoverRequest(Credentials):
    limit: int = Field(default=100, ge=1, le=500)


class IngestRequest(Credentials):
    track_ids: list[str] = Field(min_length=1, max_length=20000)


class SyncRequest(BaseModel):
    mode: str = Field(default="all", pattern="^(all|missing)$")


class OidcPolicyRequest(BaseModel):
    auto_provision: bool


class OidcAllowRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class OidcUserUpdateRequest(BaseModel):
    is_admin: bool | None = None
    is_blocked: bool | None = None


class ProfileSettingsRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)


class TimezoneSettingsRequest(BaseModel):
    timezone: str = Field(min_length=1, max_length=100)


class LastFmSettingsRequest(BaseModel):
    username: str = Field(min_length=1, max_length=120)
    api_key: SecretStr


class KaraokeProcessingSettingsRequest(BaseModel):
    enabled: bool


class HumProcessingSettingsRequest(BaseModel):
    enabled: bool


class OnboardingPreference(BaseModel):
    complete: bool = True
    connection_id: uuid.UUID | None = None


class ConceptRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=500)
    positive_prompts: list[str] = Field(default_factory=list, max_length=12)
    negative_prompts: list[str] = Field(default_factory=list, max_length=12)
    positive_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    negative_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)


class ConceptPreviewRequest(BaseModel):
    positive_prompts: list[str] = Field(default_factory=list, max_length=12)
    negative_prompts: list[str] = Field(default_factory=list, max_length=12)
    positive_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    negative_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=50, ge=1, le=200)


class ConceptLensRequest(BaseModel):
    concepts: list[str] = Field(min_length=1, max_length=6)
    minimum_percentile: float = Field(default=0.5, ge=0, le=1)
    representation: str = Field(default="hybrid", pattern="^(semantic|lyrics|hybrid)$")


class CurationPreviewRequest(BaseModel):
    curation_type: str = Field(default="language", pattern="^(language|examples|time_of_day)$")
    positive_prompt: str = Field(default="", max_length=2000)
    negative_prompt: str = Field(default="", max_length=2000)
    sound_prompts: list[str] = Field(default_factory=list, max_length=12)
    themes_prompts: list[str] = Field(default_factory=list, max_length=12)
    sound_negative_prompts: list[str] = Field(default_factory=list, max_length=12)
    themes_negative_prompts: list[str] = Field(default_factory=list, max_length=12)
    sound_weight: int = Field(default=50, ge=0, le=100)
    positive_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    negative_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=20)
    familiarity_percent: int = Field(default=70, ge=0, le=100)
    period_start: str | None = Field(default=None, pattern="^(?:[01]\\d|2[0-3]):[0-5]\\d$")
    period_end: str | None = Field(default=None, pattern="^(?:[01]\\d|2[0-3]):[0-5]\\d$")
    lookback_days: int = Field(default=7, ge=1, le=90)
    track_limit: int = Field(default=30, ge=5, le=200)
    refresh_mode: str = Field(default="stable", pattern="^(stable|fresh)$")
    existing_track_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class CurationCreateRequest(CurationPreviewRequest):
    name: str = Field(min_length=1, max_length=120)
    refresh_enabled: bool = True


class CurationUpdateRequest(BaseModel):
    refresh_enabled: bool | None = None
    refresh_mode: str | None = Field(default=None, pattern="^(stable|fresh)$")
    track_limit: int | None = Field(default=None, ge=5, le=200)
    familiarity_percent: int | None = Field(default=None, ge=0, le=100)


class JourneyRequest(BaseModel):
    start_track_id: uuid.UUID
    end_track_id: uuid.UUID
    mode: str = Field(default="semantic", pattern="^(semantic|acoustic|blend)$")
    semantic_weight: float = Field(default=0.5, ge=0, le=1)
    length: int = Field(default=15, ge=3, le=50)


def _credentials(request: Credentials) -> tuple[str, str, str]:
    return str(request.url).rstrip("/"), request.username, request.password.get_secret_value()


def _cipher() -> Fernet:
    key = os.environ.get("CREDENTIAL_ENCRYPTION_KEY")
    if not key:
        raise RuntimeError("CREDENTIAL_ENCRYPTION_KEY is required")
    return Fernet(key.encode())


def _save_connection(credentials: tuple[str, str, str], user_id: uuid.UUID) -> str:
    url, username, password = credentials
    encrypted = _cipher().encrypt(password.encode())
    with session_scope() as session:
        stored = session.scalar(select(NavidromeConnection).where(
            NavidromeConnection.owner_user_id == user_id,
            NavidromeConnection.url == url, NavidromeConnection.username == username,
        ))
        if stored is None:
            stored = NavidromeConnection(url=url, username=username, encrypted_password=encrypted, owner_user_id=user_id)
            session.add(stored)
            session.flush()
        else:
            stored.encrypted_password = encrypted
            stored.last_used_at = datetime.now(timezone.utc)
        return str(stored.id)


def _attach_user_library(user_id: uuid.UUID, source_url: str) -> None:
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, source_url.rstrip("/"))
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO user_libraries (user_id, library_id)
               SELECT %s, id FROM libraries WHERE namespace=%s
               ON CONFLICT DO NOTHING""",
            (user_id, namespace),
        )


def _reconcile_user_tracks(user_id: uuid.UUID, source_url: str, external_ids: list[str]) -> dict[str, int]:
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, source_url.rstrip("/"))
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT id FROM libraries WHERE namespace=%s", (namespace,))
        library = cursor.fetchone()
        if library is None:
            return {"linked": 0, "unlinked": 0}
        library_id = library["id"]
        cursor.execute(
            """DELETE FROM user_track_links
               WHERE user_id=%s AND library_id=%s AND NOT (external_id = ANY(%s))""",
            (user_id, library_id, external_ids),
        )
        unlinked = cursor.rowcount
        cursor.execute(
            """INSERT INTO user_track_links (user_id, library_id, track_id, external_id)
               SELECT %s, ts.library_id, ts.track_id, ts.external_id
               FROM track_sources ts
               WHERE ts.library_id=%s AND ts.source_type='subsonic' AND ts.external_id=ANY(%s)
               ON CONFLICT (user_id, library_id, track_id) DO UPDATE
               SET external_id=EXCLUDED.external_id, last_seen_at=now()""",
            (user_id, library_id, external_ids),
        )
        cursor.execute("SELECT count(*) AS count FROM user_track_links WHERE user_id=%s AND library_id=%s", (user_id, library_id))
        linked = int(cursor.fetchone()["count"])
    return {"linked": linked, "unlinked": unlinked}


def _load_connection(connection_id: str, user_id: uuid.UUID | None = None) -> tuple[str, str, str] | None:
    try:
        identifier = uuid.UUID(connection_id)
    except ValueError:
        return None
    with session_scope() as session:
        filters = [NavidromeConnection.id == identifier]
        if user_id is not None:
            filters.append(NavidromeConnection.owner_user_id == user_id)
        stored = session.scalar(select(NavidromeConnection).where(*filters))
        if stored is None:
            return None
        stored.last_used_at = datetime.now(timezone.utc)
        url, username, encrypted_password = stored.url, stored.username, bytes(stored.encrypted_password)
    try:
        password = _cipher().decrypt(encrypted_password).decode()
    except InvalidToken as error:
        raise RuntimeError("Stored Navidrome credentials cannot be decrypted") from error
    return url, username, password


def _run_lyrics_backfill(
    job_id: str, credentials: tuple[str, str, str], external_ids: list[str] | None = None,
    only_missing: bool = False, base_summary: dict[str, int] | None = None,
) -> None:
    def progress(update: dict[str, object]) -> None:
        with _jobs_lock:
            _jobs[job_id] = {**_jobs[job_id], **update, "status": "running"}
    try:
        summary = backfill_lyrics(
            *credentials, progress=progress, external_ids=external_ids, only_missing=only_missing,
        )
        karaoke_summary = backfill_karaoke(*credentials, progress=progress, external_ids=external_ids)
        voice_summary = backfill_voice(*credentials, progress=progress)
        combined = {**(base_summary or {}),
                    **{f"lyrics_{key}": value for key, value in summary.items()},
                    **{f"karaoke_{key}": value for key, value in karaoke_summary.items()},
                    **{f"voice_{key}": value for key, value in voice_summary.items()}}
        with _jobs_lock:
            _jobs[job_id] = {"status": "complete", "phase": "complete", "message": "Audio, lyrics, and voice analysis is complete",
                             "completed": summary["total"], "total": summary["total"], "unit": "tracks", "summary": combined}
    except Exception as error:
        logger.exception("Lyrics backfill failed")
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "phase": "failed", "error": str(error)}


def _run_voice_backfill(job_id: str, credentials: tuple[str, str, str]) -> None:
    def progress(update: dict[str, object]) -> None:
        with _jobs_lock:
            _jobs[job_id] = {**_jobs[job_id], **update, "status": "running"}
    try:
        summary = backfill_voice(*credentials, progress=progress)
        with _jobs_lock:
            _jobs[job_id] = {"status": "complete", "phase": "complete",
                             "message": "Voice classification is complete",
                             "completed": summary["total"], "total": summary["total"],
                             "unit": "tracks", "summary": summary}
    except Exception as error:
        logger.exception("Voice backfill failed")
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "phase": "failed", "error": str(error)}


def _run_karaoke_backfill(job_id: str, credentials: tuple[str, str, str]) -> None:
    def progress(update: dict[str, object]) -> None:
        with _jobs_lock:
            _jobs[job_id] = {**_jobs[job_id], **update, "status": "running"}
    try:
        summary = backfill_karaoke(*credentials, progress=progress)
        with _jobs_lock:
            _jobs[job_id] = {"status": "complete", "phase": "complete",
                             "message": "Karaoke lyric alignment is complete",
                             "completed": summary["total"], "total": summary["total"],
                             "unit": "tracks", "summary": summary}
    except Exception as error:
        logger.exception("FA-Kara backfill failed")
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "phase": "failed", "error": str(error)}


def _run_fingerprint_backfill(job_id: str, credentials: tuple[str, str, str]) -> None:
    url, username, password = credentials
    try:
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection, NavidromeClient(url, username, password) as client:
            with connection.cursor() as cursor:
                cursor.execute(
                    """SELECT ts.track_id, ts.external_id, t.duration_seconds, t.title
                       FROM track_sources ts JOIN tracks t ON t.id=ts.track_id
                       LEFT JOIN track_fingerprints tf ON tf.track_id=t.id
                       WHERE ts.source_type='subsonic' AND tf.track_id IS NULL ORDER BY t.id"""
                )
                tracks = cursor.fetchall()
            with _jobs_lock:
                _jobs[job_id] = {"status": "running", "phase": "fingerprinting", "completed": 0, "total": len(tracks)}
            matched = 0
            failed = 0
            for index, (track_id, external_id, duration, title) in enumerate(tracks):
                try:
                    audio = client.audio_bytes(external_id)
                    result = store_and_match_fingerprint(connection, track_id, audio, float(duration))
                    matched += int(bool(result.get("matched")))
                    connection.commit()
                except Exception:
                    connection.rollback()
                    failed += 1
                    logger.exception("Fingerprint backfill failed for %s", track_id)
                with _jobs_lock:
                    _jobs[job_id] = {"status": "running", "phase": "fingerprinting", "completed": index + 1,
                                     "total": len(tracks), "message": f"Fingerprinting {title}",
                                     "matched": matched, "failed": failed}
            with _jobs_lock:
                _jobs[job_id] = {"status": "complete", "phase": "complete", "completed": len(tracks),
                                 "total": len(tracks), "matched": matched, "failed": failed}
    except Exception as error:
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "phase": "failed", "error": str(error)}


def _lyrics_work_count(external_ids: list[str]) -> int:
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection:
        lyrics = plan_lyrics(connection, external_ids).lyrics_external_ids
        karaoke = plan_karaoke(connection, KARAOKE_PIPELINE_REVISION, external_ids).karaoke_external_ids
    return len(set(lyrics) | set(karaoke))


def _run_ingest(
    job_id: str, request: IngestRequest, user_id: uuid.UUID | None = None,
    catalog_ids: list[str] | None = None, include_lyrics: bool = False,
) -> None:
    def progress(update: dict[str, object]) -> None:
        with _jobs_lock:
            current = _jobs[job_id]
            _jobs[job_id] = {**current, **update, "status": "running"}

    with _jobs_lock:
        _jobs[job_id] = {
            **_jobs[job_id], "status": "running", "phase": "starting",
            "completed": 0, "total": len(request.track_ids),
        }
    try:
        summary = ingest_navidrome(
            *_credentials(request), request.track_ids, progress, model_total=4 if include_lyrics else 2,
        )
        reconciliation = {"linked": 0, "unlinked": 0}
        if user_id is not None:
            _attach_user_library(user_id, str(request.url))
            reconciliation = _reconcile_user_tracks(user_id, str(request.url), catalog_ids or request.track_ids)
        combined = {**asdict(summary), **reconciliation}
        lyrics_ids = catalog_ids or request.track_ids
        if include_lyrics:
            lyrics_summary = backfill_lyrics(
                *_credentials(request), progress=progress, external_ids=lyrics_ids, only_missing=True,
            )
            combined.update({f"lyrics_{key}": value for key, value in lyrics_summary.items()})
            # Refresh after lyrics retrieval because newly synced lines can create
            # karaoke work. Each pipeline plans before loading its model.
            karaoke_summary = backfill_karaoke(
                *_credentials(request), progress=progress, external_ids=lyrics_ids,
            )
            combined.update({f"karaoke_{key}": value for key, value in karaoke_summary.items()})
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "complete", "phase": "complete", "message": "Audio and lyrics analysis is complete",
                "completed": len(request.track_ids), "total": len(request.track_ids), "unit": "tracks",
                "summary": combined,
            }
    except Exception as error:
        logger.exception("Ingest failed")
        with _jobs_lock:
            _jobs[job_id] = {**_jobs[job_id], "status": "failed", "error": str(error)}


def _run_hum_corpus(
    job_id: str, corpus_id: uuid.UUID, user_id: uuid.UUID,
    credentials: tuple[str, str, str], track_limit: int,
) -> None:
    def progress(update: dict[str, object]) -> None:
        with _jobs_lock:
            _jobs[job_id] = {**_jobs[job_id], **update, "status": "running"}
    try:
        summary = build_corpus(corpus_id, user_id, credentials, track_limit, progress)
        with _jobs_lock:
            _jobs[job_id] = {
                "status": "complete", "phase": "complete", "completed": summary["tracks"],
                "total": track_limit, "summary": summary, "corpus_id": str(corpus_id),
            }
    except Exception as error:
        logger.exception("Hum corpus build failed")
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
            cursor.execute(
                "UPDATE hum_corpora SET status='failed', error=%s WHERE id=%s",
                (str(error), corpus_id),
            )
        with _jobs_lock:
            _jobs[job_id] = {"status": "failed", "phase": "failed", "error": str(error)}


def require_user(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    return _session_user(echora_session)


def _session_user(token: str | None) -> dict[str, object]:
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    with session_scope() as session:
        stored = session.scalar(
            select(UserSession).join(UserSession.user).options(joinedload(UserSession.user).joinedload(User.preference))
            .where(UserSession.token_hash == token_hash, UserSession.expires_at > datetime.now(timezone.utc), User.is_blocked.is_(False))
        )
        if stored is None or stored.user.preference is None:
            raise HTTPException(status_code=401, detail="Session expired")
        user, preference = stored.user, stored.user.preference
        return {
            "id": user.id, "username": user.username, "email": user.email,
            "display_name": user.display_name, "is_admin": user.is_admin,
            "onboarding_complete": preference.onboarding_complete,
            "navidrome_connection_id": preference.navidrome_connection_id,
        }


def _recover_interrupted_curations() -> None:
    """Mark refreshes owned by a previous process as failed.

    A refresh cannot survive an analysis-service restart. Leaving the durable
    row in `refreshing` makes the UI imply work is still running when no worker
    owns it, so fail it explicitly and let the user or scheduler retry.
    """
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
        cursor.execute(
            """UPDATE curations
               SET status='failed',
                   last_error='Refresh interrupted by analysis service restart',
                   updated_at=now()
               WHERE status='refreshing'"""
        )


@app.on_event("startup")
def start_background_services() -> None:
    global _scheduler_started
    _enforce_secure_cookie_policy()
    _recover_interrupted_curations()
    if not _scheduler_started:
        _scheduler_started = True
        threading.Thread(target=_curation_scheduler, name="echora-curations", daemon=True).start()


def _enforce_secure_cookie_policy() -> None:
    if os.environ.get("COOKIE_SECURE", "false").lower() == "true":
        return
    redirect = os.environ.get("OIDC_REDIRECT_URI", "http://localhost:3000/analysis/auth/oidc/callback")
    host = urlparse(redirect).hostname or ""
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise RuntimeError(
            "COOKIE_SECURE must be true when OIDC_REDIRECT_URI is not localhost; "
            "session cookies would otherwise be sent over plain HTTP"
        )


@app.get("/auth/oidc/status")
def oidc_status() -> dict[str, object]:
    return {"configured": _oauth.create_client("oidc") is not None, "provider": "OIDC"}


@app.get("/auth/oidc/start")
async def oidc_start(request: Request) -> Response:
    client = _oauth.create_client("oidc")
    if client is None:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    redirect_uri = os.environ.get("OIDC_REDIRECT_URI") or str(request.url_for("oidc_callback"))
    return await client.authorize_redirect(request, redirect_uri)


@app.get("/auth/oidc/callback", name="oidc_callback")
async def oidc_callback(request: Request) -> Response:
    client = _oauth.create_client("oidc")
    if client is None:
        raise HTTPException(status_code=503, detail="OIDC is not configured")
    try:
        token_data = await client.authorize_access_token(request)
        claims = token_data.get("userinfo") or await client.userinfo(token=token_data)
    except OAuthError as error:
        logger.warning("OIDC authentication failed: %s", error.error)
        raise HTTPException(status_code=401, detail="OIDC authentication failed") from error
    subject = str(claims.get("sub") or "").strip()
    email = str(claims.get("email") or "").strip().casefold()
    if not subject or not email or "@" not in email:
        raise HTTPException(status_code=422, detail="OIDC must provide subject and email claims")
    require_verified = os.environ.get("OIDC_REQUIRE_VERIFIED_EMAIL", "false").lower() == "true"
    if require_verified and claims.get("email_verified") is not True:
        raise HTTPException(status_code=403, detail="OIDC email is not verified")
    bootstrap_email = os.environ.get("OIDC_BOOTSTRAP_ADMIN_EMAIL", "").strip().casefold()
    if not bootstrap_email:
        raise HTTPException(status_code=503, detail="OIDC_BOOTSTRAP_ADMIN_EMAIL is not configured")
    with session_scope() as session:
        user = session.scalar(select(User).where((User.oidc_subject == subject) | (func.lower(User.email) == email)))
        admin_exists = session.scalar(select(func.count()).select_from(User).where(User.is_admin)) > 0
        if user is None:
            policy = session.get(OidcSetting, True)
            allowed = session.get(OidcAllowedEmail, email)
            if not admin_exists and email != bootstrap_email:
                raise HTTPException(status_code=403, detail="The bootstrap administrator must sign in first")
            if admin_exists and not (policy and policy.auto_provision) and allowed is None:
                raise HTTPException(status_code=403, detail="Your email has not been approved by an administrator")
            display_name = str(claims.get("name") or claims.get("preferred_username") or email).strip()
            user = User(
                username=email, email=email, display_name=display_name, password_hash=None,
                oidc_subject=subject, is_admin=not admin_exists and email == bootstrap_email,
            )
            user.preference = UserPreference()
            session.add(user)
            session.flush()
            if allowed is not None:
                session.delete(allowed)
        else:
            if user.is_blocked:
                raise HTTPException(status_code=403, detail="This Echora account is blocked")
            if user.oidc_subject and user.oidc_subject != subject:
                raise HTTPException(status_code=409, detail="This email is linked to another OIDC identity")
            user.oidc_subject = subject
            user.email = email
            user.username = email
        token = secrets.token_urlsafe(48)
        session.execute(delete(UserSession).where(UserSession.expires_at < datetime.now(timezone.utc)))
        session.add(UserSession(
            token_hash=hashlib.sha256(token.encode()).hexdigest(), user_id=user.id,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=_SESSION_HOURS),
        ))
    destination = os.environ.get("OIDC_POST_LOGIN_REDIRECT", "http://localhost:3000/home")
    response = RedirectResponse(destination, status_code=303)
    response.set_cookie("echora_session", token, max_age=_SESSION_HOURS * 3600, httponly=True, samesite="strict", secure=os.environ.get("COOKIE_SECURE", "false").lower() == "true", path="/")
    return response


@app.post("/auth/logout", status_code=204)
def logout(response: Response, echora_session: str | None = Cookie(default=None)) -> Response:
    if echora_session:
        with session_scope() as session:
            session.execute(delete(UserSession).where(UserSession.token_hash == hashlib.sha256(echora_session.encode()).hexdigest()))
    response.delete_cookie("echora_session", path="/")
    return response


@app.get("/auth/me")
def me(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    return {key: user[key] for key in ("username", "email", "display_name", "is_admin", "onboarding_complete", "navidrome_connection_id")}


@app.put("/users/me/preferences/onboarding")
def save_onboarding(preference: OnboardingPreference, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with session_scope() as session:
        stored = session.get(UserPreference, user["id"])
        if stored is None:
            raise HTTPException(status_code=404, detail="User preferences are unavailable")
        stored.onboarding_complete = preference.complete
        selected = session.get(NavidromeConnection, preference.connection_id) if preference.connection_id else None
        if selected is not None and selected.owner_user_id != user["id"]:
            raise HTTPException(status_code=404, detail="Connection not found")
        stored.navidrome_connection_id = preference.connection_id
        stored.updated_at = datetime.now(timezone.utc)
        selected_url = selected.url if selected else None
    if selected_url is not None:
        _attach_user_library(user["id"], selected_url)
    return {"onboarding_complete": preference.complete, "navidrome_connection_id": preference.connection_id}


@app.get("/settings")
def settings(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with session_scope() as session:
        stored_user = session.get(User, user["id"])
        preference = session.get(UserPreference, user["id"])
        connection = session.get(NavidromeConnection, preference.navidrome_connection_id) if preference and preference.navidrome_connection_id else None
        if stored_user is None or preference is None:
            raise HTTPException(status_code=404, detail="User settings are unavailable")
        model_settings = session.execute(text(
            """SELECT karaoke_processing_enabled, hum_processing_enabled
               FROM analysis_settings WHERE singleton=true"""
        )).one_or_none()
        karaoke_enabled = True if model_settings is None else bool(model_settings[0])
        hum_enabled = True if model_settings is None else bool(model_settings[1])
        return {
            "profile": {"username": stored_user.username, "email": stored_user.email, "display_name": stored_user.display_name, "is_admin": stored_user.is_admin},
            "models": {
                "karaoke_processing_enabled": karaoke_enabled,
                "hum_processing_enabled": hum_enabled,
            },
            "timezone": preference.timezone,
            "navidrome": None if connection is None else {
                "id": str(connection.id), "url": connection.url, "username": connection.username,
            },
            "lastfm": {"connected": bool(preference.lastfm_username and preference.lastfm_api_key_encrypted), "username": preference.lastfm_username},
        }


@app.put("/settings/models/karaoke")
def update_karaoke_processing_settings(
    request: KaraokeProcessingSettingsRequest, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access required")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_settings
                 (singleton, karaoke_processing_enabled, karaoke_bound_to_synced_lines, updated_at)
               VALUES (true,%s,false,now()) ON CONFLICT (singleton) DO UPDATE
               SET karaoke_processing_enabled=EXCLUDED.karaoke_processing_enabled,
                   karaoke_bound_to_synced_lines=false, updated_at=now()""",
            (request.enabled,),
        )
        pending = 0
        if request.enabled:
            cursor.execute(
                """SELECT count(*) AS pending FROM lyrics l
                   WHERE l.text IS NOT NULL AND coalesce((l.provenance->>'synced')::boolean,false)
                     AND NOT EXISTS (SELECT 1 FROM karaoke_lyrics_variants kv
                                     WHERE kv.track_id=l.track_id AND kv.bounded=false
                                       AND kv.provenance->>'pipeline_revision'=%s)""",
                (KARAOKE_PIPELINE_REVISION,),
            )
            pending = int(cursor.fetchone()["pending"])
    return {"enabled": request.enabled, "pending": pending}


@app.put("/settings/models/hum")
def update_hum_processing_settings(
    request: HumProcessingSettingsRequest, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    if not user.get("is_admin"):
        raise HTTPException(status_code=403, detail="Administrator access required")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO analysis_settings
                 (singleton, karaoke_bound_to_synced_lines, hum_processing_enabled, updated_at)
               VALUES (true,false,%s,now()) ON CONFLICT (singleton) DO UPDATE
               SET hum_processing_enabled=EXCLUDED.hum_processing_enabled,
                   karaoke_bound_to_synced_lines=false, updated_at=now()""",
            (request.enabled,),
        )
        pending = 0
        if request.enabled:
            cursor.execute(
                """SELECT count(DISTINCT ts.track_id) AS pending
                   FROM track_sources ts
                   WHERE ts.source_type='subsonic'
                     AND NOT EXISTS (
                       SELECT 1 FROM melody_contours mc
                       JOIN analysis_runs ar ON ar.id=mc.run_id
                       WHERE mc.track_id=ts.track_id
                         AND ar.model_name='melody_contour' AND ar.model_revision=%s
                     )""",
                (MELODY_CONTOUR_REVISION,),
            )
            pending = int(cursor.fetchone()["pending"])
    return {"enabled": request.enabled, "pending": pending}


@app.put("/settings/profile")
def update_profile(request: ProfileSettingsRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, str]:
    user = _session_user(echora_session)
    with session_scope() as session:
        stored = session.get(User, user["id"])
        if stored is None:
            raise HTTPException(status_code=404, detail="User not found")
        stored.display_name = request.display_name.strip()
    return {"display_name": request.display_name.strip()}


@app.put("/settings/timezone")
def update_timezone(request: TimezoneSettingsRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, str]:
    user = _session_user(echora_session)
    try:
        ZoneInfo(request.timezone)
    except ZoneInfoNotFoundError as error:
        raise HTTPException(status_code=422, detail="Unknown timezone") from error
    with session_scope() as session:
        preference = session.get(UserPreference, user["id"])
        if preference is None:
            raise HTTPException(status_code=404, detail="User preferences are unavailable")
        preference.timezone = request.timezone
        preference.updated_at = datetime.now(timezone.utc)
    return {"timezone": request.timezone}


@app.put("/settings/navidrome")
def update_navidrome(request: Credentials, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _credentials(request)
    try:
        with NavidromeClient(*credentials) as client:
            version = client.ping()
    except Exception as error:
        logger.warning("Navidrome connection test failed for %s: %s", request.url, error)
        raise HTTPException(status_code=422, detail="Could not connect to Navidrome") from error
    connection_id = uuid.UUID(_save_connection(credentials, user["id"]))
    with session_scope() as session:
        preference = session.get(UserPreference, user["id"])
        if preference is None:
            raise HTTPException(status_code=404, detail="User preferences are unavailable")
        preference.navidrome_connection_id = connection_id
        preference.updated_at = datetime.now(timezone.utc)
    _attach_user_library(user["id"], credentials[0])
    return {"id": connection_id, "url": credentials[0], "username": credentials[1], "server": version}


@app.put("/settings/lastfm")
def update_lastfm(request: LastFmSettingsRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    api_key = request.api_key.get_secret_value().strip()
    try:
        response = httpx.get("https://ws.audioscrobbler.com/2.0/", params={
            "method": "user.getrecenttracks", "user": request.username.strip(),
            "api_key": api_key, "format": "json", "limit": 1,
        }, timeout=15)
        response.raise_for_status()
        payload = response.json()
        if payload.get("error"):
            raise ValueError(str(payload.get("message") or "Last.fm rejected these settings"))
        total = int(payload.get("recenttracks", {}).get("@attr", {}).get("total") or 0)
    except Exception as error:
        logger.warning("Last.fm verification failed for %s: %s", request.username, error)
        raise HTTPException(status_code=422, detail="Could not verify the Last.fm account") from error
    with session_scope() as session:
        preference = session.get(UserPreference, user["id"])
        if preference is None:
            raise HTTPException(status_code=404, detail="User preferences are unavailable")
        preference.lastfm_username = request.username.strip()
        preference.lastfm_api_key_encrypted = _cipher().encrypt(api_key.encode())
        preference.updated_at = datetime.now(timezone.utc)
    return {"connected": True, "username": request.username.strip(), "scrobbles": total}


@app.delete("/settings/lastfm", status_code=204)
def disconnect_lastfm(response: Response, echora_session: str | None = Cookie(default=None)) -> Response:
    user = _session_user(echora_session)
    with session_scope() as session:
        preference = session.get(UserPreference, user["id"])
        if preference is not None:
            preference.lastfm_username = None
            preference.lastfm_api_key_encrypted = None
            preference.updated_at = datetime.now(timezone.utc)
    return response


def _admin_user(echora_session: str | None) -> dict[str, object]:
    user = _session_user(echora_session)
    if not user["is_admin"]:
        raise HTTPException(status_code=403, detail="Administrator access is required")
    return user


@app.get("/settings/oidc")
def oidc_admin_settings(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    _admin_user(echora_session)
    with session_scope() as session:
        policy = session.get(OidcSetting, True)
        users = session.scalars(select(User).where(User.email.is_not(None)).order_by(func.lower(User.email))).all()
        allowed = session.scalars(select(OidcAllowedEmail).order_by(OidcAllowedEmail.email)).all()
        return {
            "configured": _oauth.create_client("oidc") is not None,
            "issuer": _oidc_issuer or None,
            "require_verified_email": os.environ.get("OIDC_REQUIRE_VERIFIED_EMAIL", "false").lower() == "true",
            "auto_provision": policy.auto_provision if policy else True,
            "users": [{
                "id": str(item.id), "email": item.email, "display_name": item.display_name,
                "is_admin": item.is_admin, "is_blocked": item.is_blocked,
            } for item in users],
            "allowed_emails": [item.email for item in allowed],
        }


@app.put("/settings/oidc/policy")
def update_oidc_policy(request: OidcPolicyRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, bool]:
    _admin_user(echora_session)
    with session_scope() as session:
        policy = session.get(OidcSetting, True)
        if policy is None:
            policy = OidcSetting(singleton=True)
            session.add(policy)
        policy.auto_provision = request.auto_provision
        policy.updated_at = datetime.now(timezone.utc)
    return {"auto_provision": request.auto_provision}


@app.post("/settings/oidc/allowed-emails", status_code=201)
def allow_oidc_email(request: OidcAllowRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, str]:
    admin = _admin_user(echora_session)
    email = request.email.strip().casefold()
    if "@" not in email:
        raise HTTPException(status_code=422, detail="Enter a valid email address")
    with session_scope() as session:
        if session.scalar(select(User.id).where(func.lower(User.email) == email)):
            raise HTTPException(status_code=409, detail="This user already exists")
        if session.get(OidcAllowedEmail, email) is None:
            session.add(OidcAllowedEmail(email=email, created_by=admin["id"]))
    return {"email": email}


@app.delete("/settings/oidc/allowed-emails/{email}", status_code=204)
def remove_allowed_oidc_email(email: str, response: Response, echora_session: str | None = Cookie(default=None)) -> Response:
    _admin_user(echora_session)
    with session_scope() as session:
        allowed = session.get(OidcAllowedEmail, email.casefold())
        if allowed is not None:
            session.delete(allowed)
    return response


@app.patch("/settings/oidc/users/{user_id}")
def update_oidc_user(
    user_id: uuid.UUID, request: OidcUserUpdateRequest,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    admin = _admin_user(echora_session)
    values = request.model_dump(exclude_none=True)
    with session_scope() as session:
        target = session.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="User not found")
        if user_id == admin["id"] and (values.get("is_admin") is False or values.get("is_blocked") is True):
            raise HTTPException(status_code=422, detail="You cannot demote or block your own account")
        if target.is_admin and values.get("is_admin") is False:
            admin_count = session.scalar(select(func.count()).select_from(User).where(User.is_admin, User.is_blocked.is_(False)))
            if admin_count <= 1:
                raise HTTPException(status_code=422, detail="Echora must retain at least one active administrator")
        for key, value in values.items():
            setattr(target, key, value)
        if values.get("is_blocked") is True:
            session.execute(delete(UserSession).where(UserSession.user_id == user_id))
        return {"id": str(target.id), **values}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "echora-analysis"}


@app.get("/capabilities")
def capabilities() -> dict[str, object]:
    return {
        "models": {
            "muq_mulan": {"status": "available", "audio": True, "text": True},
            "mert": {"status": "available", "audio": True, "text": False},
            "heartclap": {"status": "blocked-upstream-release", "audio": False, "text": False},
        }
    }


@app.post("/navidrome/discover", dependencies=[Depends(require_user)])
def discover(request: DiscoverRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    try:
        with NavidromeClient(*_credentials(request)) as client:
            version = client.ping()
            tracks = client.random_tracks(request.limit)
    except Exception as error:
        logger.warning("Navidrome discovery failed for %s: %s", request.url, error)
        raise HTTPException(status_code=400, detail="Could not connect to the Navidrome server") from error
    connection_id = _save_connection(_credentials(request), user["id"])
    return {
        "connection_id": connection_id,
        "server": {"version": version, "url": str(request.url).rstrip("/")},
        "tracks": [
            {
                "id": track.id, "title": track.title, "artist": track.artist,
                "album": track.album, "duration": track.duration, "genre": track.genre,
                "cover_art": track.raw.get("coverArt"),
            }
            for track in tracks
        ],
    }


@app.get("/navidrome/connections/{connection_id}/catalog", dependencies=[Depends(require_user)])
def navidrome_catalog(connection_id: str, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        with NavidromeClient(*credentials) as client:
            return client.catalog()
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not read the Navidrome catalog") from error


@app.get("/navidrome/connections/{connection_id}/sync/status", dependencies=[Depends(require_user)])
def navidrome_sync_status(connection_id: str, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        with NavidromeClient(*credentials) as client:
            tracks = client.all_tracks()
    except Exception as error:
        raise HTTPException(status_code=502, detail="Could not scan the Navidrome library") from error
    namespace = uuid.uuid5(uuid.NAMESPACE_URL, credentials[0].rstrip("/"))
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT ts.external_id FROM track_sources ts
            JOIN libraries l ON l.id=ts.library_id
            WHERE l.namespace=%s AND ts.source_type='subsonic'
            """,
            (namespace,),
        )
        processed = {str(row[0]) for row in cursor.fetchall()}
    missing = [track for track in tracks if track.id not in processed]
    return {
        "server": credentials[0], "total": len(tracks), "processed": len(tracks) - len(missing), "missing": len(missing),
        "tracks": [{"id": track.id, "title": track.title, "artist": track.artist, "album": track.album, "duration": track.duration, "cover_art": track.raw.get("coverArt")} for track in missing[:50]],
    }


@app.post("/navidrome/connections/{connection_id}/sync", status_code=202)
def start_navidrome_sync(
    connection_id: str, request: SyncRequest, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    with _jobs_lock:
        for active_job_id, active_job in _jobs.items():
            if (
                active_job.get("_job_type") == "navidrome_sync"
                and active_job.get("_connection_id") == connection_id
                and active_job.get("_user_id") == str(user["id"])
                and active_job.get("status") in {"queued", "running"}
            ):
                return {
                    "job_id": active_job_id, "status": active_job["status"],
                    "total": int(active_job.get("total", 0)), "existing": True,
                }
        job_id = str(uuid.uuid4())
        _jobs[job_id] = {
            "status": "queued", "phase": "scanning", "completed": 0, "total": 0,
            "unit": "tracks", "_job_type": "navidrome_sync",
            "_connection_id": connection_id, "_user_id": str(user["id"]),
        }
    try:
        with NavidromeClient(*credentials) as client:
            tracks = client.all_tracks()
    except Exception as error:
        with _jobs_lock:
            _jobs[job_id] = {**_jobs[job_id], "status": "failed", "phase": "failed", "error": str(error)}
        raise HTTPException(status_code=502, detail="Could not scan the Navidrome library") from error
    catalog_ids = [track.id for track in tracks]
    _attach_user_library(user["id"], credentials[0])
    reconciliation = _reconcile_user_tracks(user["id"], credentials[0], catalog_ids)
    # The ingestion planner selects missing representations per track. Keep the
    # full catalog here so a sync can backfill newly added analysis phases.
    if not tracks:
        lyrics_total = _lyrics_work_count(catalog_ids)
        if lyrics_total:
            with _jobs_lock:
                _jobs[job_id] = {**_jobs[job_id], "phase": "queued", "total": lyrics_total}
            _executor.submit(_run_lyrics_backfill, job_id, credentials, catalog_ids, True, reconciliation)
            return {"job_id": job_id, "status": "queued", "total": lyrics_total, "unlinked": reconciliation["unlinked"]}
        with _jobs_lock:
            _jobs[job_id] = {
                **_jobs[job_id], "status": "complete", "phase": "complete",
                "message": "Library links, audio, and lyrics are synchronized", "summary": reconciliation,
            }
        return {
            "status": "complete", "message": "Library links, audio, and lyrics are synchronized", "total": 0,
            "summary": reconciliation,
        }
    ingest_request = IngestRequest(url=credentials[0], username=credentials[1], password=credentials[2], track_ids=[track.id for track in tracks])
    with _jobs_lock:
        _jobs[job_id] = {**_jobs[job_id], "phase": "queued", "total": len(tracks)}
    _executor.submit(_run_ingest, job_id, ingest_request, user["id"], catalog_ids, True)
    return {"job_id": job_id, "status": "queued", "total": len(tracks), "unlinked": reconciliation["unlinked"]}


@app.post("/navidrome/connections/{connection_id}/recordings/backfill", status_code=202, dependencies=[Depends(require_user)])
def start_recording_backfill(
    connection_id: str, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM tracks t LEFT JOIN track_fingerprints f ON f.track_id=t.id WHERE f.track_id IS NULL")
        total = int(cursor.fetchone()[0])
    if total == 0:
        return {"status": "complete", "total": 0, "message": "All tracks have recording fingerprints"}
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "phase": "queued", "completed": 0, "total": total}
    _executor.submit(_run_fingerprint_backfill, job_id, credentials)
    return {"job_id": job_id, "status": "queued", "total": total}


@app.get("/library/lyrics/status", dependencies=[Depends(require_user)])
def lyrics_status(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(*) AS total,
                      count(*) FILTER (WHERE l.availability_status='available') AS available,
                      count(*) FILTER (WHERE l.availability_status='missing') AS missing,
                      count(*) FILTER (WHERE l.availability_status='unavailable') AS unavailable,
                      count(*) FILTER (WHERE l.availability_status='instrumental') AS instrumental,
                      count(*) FILTER (WHERE EXISTS (
                        SELECT 1 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                        WHERE e.track_id=t.id AND e.embedding_type='lyrics' AND e.window_index IS NULL
                          AND ar.model_name='bge_m3'
                      )) AS embedded
               FROM tracks t LEFT JOIN lyrics l ON l.track_id=t.id"""
        )
        return cursor.fetchone()


@app.post("/navidrome/connections/{connection_id}/lyrics/backfill", status_code=202, dependencies=[Depends(require_user)])
def start_lyrics_backfill(
    connection_id: str, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "phase": "queued", "completed": 0, "total": 0}
    _executor.submit(_run_lyrics_backfill, job_id, credentials)
    return {"job_id": job_id, "status": "queued"}


@app.post("/navidrome/connections/{connection_id}/voice/backfill", status_code=202, dependencies=[Depends(require_user)])
def start_voice_backfill(
    connection_id: str, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "phase": "queued", "completed": 0, "total": 0}
    _executor.submit(_run_voice_backfill, job_id, credentials)
    return {"job_id": job_id, "status": "queued"}


@app.post("/navidrome/connections/{connection_id}/lyrics/karaoke/backfill", status_code=202, dependencies=[Depends(require_user)])
def start_karaoke_backfill(
    connection_id: str, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "phase": "queued", "completed": 0, "total": 0}
    _executor.submit(_run_karaoke_backfill, job_id, credentials)
    return {"job_id": job_id, "status": "queued"}


@app.get("/library/tracks/{track_id}/recording-group", dependencies=[Depends(require_user)])
def track_recording_group(
    track_id: uuid.UUID, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT rg.id, rg.status, rg.canonical_track_id, rg.created_at, rg.updated_at
               FROM recording_group_members member JOIN recording_groups rg ON rg.id=member.group_id
               WHERE member.track_id=%s""",
            (track_id,),
        )
        group = cursor.fetchone()
        if group is None:
            cursor.execute("SELECT 1 FROM track_fingerprints WHERE track_id=%s", (track_id,))
            return {"group": None, "fingerprinted": cursor.fetchone() is not None}
        cursor.execute(
            """SELECT t.id, t.title, t.artist, t.album, t.duration_seconds, member.confidence,
                      member.membership_status, array_agg(DISTINCT ts.external_id) AS source_ids
               FROM recording_group_members member JOIN tracks t ON t.id=member.track_id
               LEFT JOIN track_sources ts ON ts.track_id=t.id WHERE member.group_id=%s
               GROUP BY t.id, member.confidence, member.membership_status ORDER BY t.title""",
            (group["id"],),
        )
        members = cursor.fetchall()
        cursor.execute(
            """SELECT id, left_track_id, right_track_id, decision, chromaprint_score,
                      duration_delta_seconds, semantic_similarity, acoustic_similarity,
                      matcher_revision, created_at FROM recording_match_evidence
               WHERE left_track_id=ANY(%s) AND right_track_id=ANY(%s) ORDER BY created_at DESC""",
            ([member["id"] for member in members], [member["id"] for member in members]),
        )
        evidence = cursor.fetchall()
    return {"group": {**group, "members": members, "evidence": evidence}, "fingerprinted": True}


@app.get("/library/tracks/{track_id}/audio-quality")
def track_audio_quality(track_id: uuid.UUID, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT ts.source_data->>'suffix' AS codec,
                      ts.source_data->>'contentType' AS content_type,
                      (ts.source_data->>'bitRate')::integer AS bit_rate_kbps,
                      (ts.source_data->>'bitDepth')::integer AS bit_depth,
                      (ts.source_data->>'samplingRate')::integer AS sample_rate_hz,
                      (ts.source_data->>'channelCount')::integer AS channels
               FROM user_track_links link
               JOIN track_sources ts ON ts.track_id=link.track_id AND ts.library_id=link.library_id
                                    AND ts.external_id=link.external_id
               WHERE link.user_id=%s AND link.track_id=%s
               ORDER BY ts.id LIMIT 1""",
            (user["id"], track_id),
        )
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Track is not in your library")
    codec = str(row.get("codec") or "").lower()
    return {**row, "lossless": codec in {"flac", "alac", "wav", "aiff", "ape", "wv"}}


@app.get("/library/tracks/{track_id}/lyrics")
def track_lyrics(track_id: uuid.UUID, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT l.text, l.language, l.source, l.provenance,
                      karaoke.lines AS karaoke_lines, karaoke.ass AS karaoke_ass,
                      karaoke.lrc AS karaoke_lrc, karaoke.model AS karaoke_model,
                      karaoke.model_revision AS karaoke_model_revision,
                      karaoke.bounded AS karaoke_bounded
               FROM user_track_links link
               LEFT JOIN lyrics l ON l.track_id=link.track_id
               LEFT JOIN LATERAL (
                 SELECT kv.* FROM karaoke_lyrics_variants kv
                 WHERE kv.track_id=link.track_id AND kv.bounded=false LIMIT 1
               ) karaoke ON true
               WHERE link.user_id=%s AND link.track_id=%s LIMIT 1""",
            (user["id"], track_id),
        )
        row = cursor.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Track is not in your library")
    provenance = row.get("provenance") or {}
    source_lines = provenance.get("lines") or []
    karaoke_lines = row.get("karaoke_lines") or []
    return {"available": bool(row.get("text")), **row,
            "lines": karaoke_lines or source_lines, "karaoke": bool(karaoke_lines)}


@app.get("/navidrome/connections/{connection_id}/stream/{song_id}", dependencies=[Depends(require_user)])
def stream_track(
    connection_id: str, song_id: str, request: Request, echora_session: str | None = Cookie(default=None),
) -> Response:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    quality = request.query_params.get("quality", "original")
    if quality not in {"original", "320", "120"}:
        raise HTTPException(status_code=422, detail="Quality must be original, 320, or 120")
    bit_rate = None if quality == "original" else int(quality)
    cache_key = (connection_id, song_id, quality)
    with _stream_cache_lock:
        cached = _stream_cache.get(cache_key)
        if cached is not None:
            _stream_cache.move_to_end(cache_key)
    range_header = request.headers.get("range")
    starts_at_zero = not range_header or range_header in {"bytes=0-", "bytes=0"}
    if cached is None and starts_at_zero:
        client = NavidromeClient(*credentials)
        try:
            upstream = client.open_transcode_stream(song_id, bit_rate, range_header)
        except Exception as error:
            client.close()
            raise HTTPException(status_code=502, detail="Could not open this track") from error
        collected = bytearray()
        content_type = upstream.headers.get("content-type", "audio/mpeg")
        def stream_and_cache():
            completed = False
            try:
                try:
                    for chunk in upstream.iter_raw(64 * 1024):
                        if len(collected) + len(chunk) <= _STREAM_CACHE_ENTRY_LIMIT:
                            collected.extend(chunk)
                        yield chunk
                except httpx.RemoteProtocolError:
                    logger.warning("Navidrome closed %s after %s bytes despite its estimated content length", song_id, len(collected))
                completed = bool(collected) and len(collected) < _STREAM_CACHE_ENTRY_LIMIT
            finally:
                upstream.close()
                client.close()
                if completed:
                    with _stream_cache_lock:
                        _stream_cache[cache_key] = (bytes(collected), content_type)
                        _stream_cache.move_to_end(cache_key)
                        while len(_stream_cache) > _STREAM_CACHE_LIMIT:
                            _stream_cache.popitem(last=False)
        forwarded = {key: value for key, value in upstream.headers.items() if key.lower() in {"content-range", "accept-ranges"}}
        return StreamingResponse(
            stream_and_cache(), status_code=upstream.status_code, media_type=content_type,
            headers={**forwarded, "Cache-Control": "no-store"},
        )
    if cached is None:
        try:
            with NavidromeClient(*credentials) as client:
                cached = client.transcode(song_id, bit_rate)
        except Exception as error:
            raise HTTPException(status_code=502, detail="Could not open this track") from error
        with _stream_cache_lock:
            if len(cached[0]) <= _STREAM_CACHE_ENTRY_LIMIT:
                _stream_cache[cache_key] = cached
                _stream_cache.move_to_end(cache_key)
                while len(_stream_cache) > _STREAM_CACHE_LIMIT:
                    _stream_cache.popitem(last=False)
    content, content_type = cached
    total = len(content)
    headers = {"Accept-Ranges": "bytes", "Cache-Control": "private, max-age=3600"}
    if range_header and range_header.startswith("bytes="):
        try:
            specification = range_header[6:].split(",", 1)[0]
            start_text, end_text = specification.split("-", 1)
            if start_text:
                start = int(start_text)
                end = min(int(end_text) if end_text else total - 1, total - 1)
            else:
                suffix = min(int(end_text), total)
                start, end = total - suffix, total - 1
            if start < 0 or start >= total or end < start:
                raise ValueError
        except ValueError as error:
            raise HTTPException(status_code=416, detail="Requested audio range is unavailable") from error
        body = content[start:end + 1]
        headers.update({"Content-Range": f"bytes {start}-{end}/{total}", "Content-Length": str(len(body))})
        return Response(body, status_code=206, media_type=content_type, headers=headers)
    headers["Content-Length"] = str(total)
    return Response(content, media_type=content_type, headers=headers)


@app.get("/navidrome/connections/{connection_id}/cover/{cover_id:path}", dependencies=[Depends(require_user)])
def cover_art(
    connection_id: str, cover_id: str, request: Request, size: int = 160,
    echora_session: str | None = Cookie(default=None),
) -> Response:
    user = _session_user(echora_session)
    credentials = _load_connection(connection_id, user["id"])
    if credentials is None:
        raise HTTPException(status_code=404, detail="Connection not found")
    try:
        with NavidromeClient(*credentials) as client:
            content, content_type = client.cover_art(cover_id, min(max(size, 64), 1600))
    except Exception as error:
        raise HTTPException(status_code=404, detail="Artwork unavailable") from error
    return Response(content=content, media_type=content_type, headers={"Cache-Control": "private, max-age=3600"})


@app.post("/ingest/navidrome", status_code=202, dependencies=[Depends(require_user)])
def start_navidrome_ingest(
    request: IngestRequest, echora_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    _session_user(echora_session)
    job_id = str(uuid.uuid4())
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "phase": "queued", "completed": 0, "total": len(request.track_ids)}
    _executor.submit(_run_ingest, job_id, request)
    return {"job_id": job_id, "status": "queued"}


@app.get("/library/hum/index", dependencies=[Depends(require_user)])
def hum_index_status(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT count(DISTINCT mc.track_id) AS indexed_tracks
               FROM melody_contours mc
               WHERE EXISTS (SELECT 1 FROM user_track_links utl
                             WHERE utl.user_id=%s AND utl.track_id=mc.track_id)""",
            (user["id"],),
        )
        indexed = int(cursor.fetchone()["indexed_tracks"])
    return {"status": "complete" if indexed else "missing", "indexed_tracks": indexed, "track_limit": indexed}


@app.post("/library/hum/index", status_code=202, dependencies=[Depends(require_user)])
def start_hum_index(
    track_limit: int = DEFAULT_CORPUS_SIZE,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, str]:
    user = _session_user(echora_session)
    track_limit = min(max(track_limit, 1), 500)
    connection_id = user.get("navidrome_connection_id")
    credentials = _load_connection(str(connection_id), user["id"]) if connection_id else None
    if credentials is None:
        raise HTTPException(status_code=409, detail="Connect Navidrome before building a hum index")
    corpus_id, job_id = uuid.uuid4(), str(uuid.uuid4())
    with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO hum_corpora (id, user_id, status, track_limit) VALUES (%s,%s,'building',%s)",
            (corpus_id, user["id"], track_limit),
        )
    with _jobs_lock:
        _jobs[job_id] = {"status": "queued", "phase": "queued", "completed": 0, "total": track_limit}
    _executor.submit(_run_hum_corpus, job_id, corpus_id, user["id"], credentials, track_limit)
    return {"job_id": job_id, "corpus_id": str(corpus_id), "status": "queued"}


@app.post("/library/hum/search", dependencies=[Depends(require_user)])
async def hum_search(
    request: Request, limit: int = 10,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="The recording is empty")
    if len(audio) > 8 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="The recording exceeds 8 MB")
    try:
        return await run_in_threadpool(
            search_corpus, user["id"], audio, min(max(limit, 1), 25),
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    except Exception as error:
        logger.exception("Hum search failed")
        raise HTTPException(status_code=500, detail="Hum search could not process this recording") from error


@app.get("/library/tracks")
def library_tracks(
    limit: int = 10, offset: int = 0, q: str = "", artist: str = "", album: str = "",
    sort_by: str = "name", echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    limit = min(max(limit, 1), 100)
    offset = max(offset, 0)
    ordering = {
        "name": "lower(t.title), lower(coalesce(t.artist, '')), t.id",
        "artist": "lower(t.artist) NULLS LAST, lower(t.title), t.id",
        "released": "t.year DESC NULLS LAST, lower(t.title), t.id",
    }.get(sort_by)
    if ordering is None:
        raise HTTPException(status_code=422, detail="Unknown track sort order")
    clauses: list[str] = [
        "EXISTS (SELECT 1 FROM user_track_links visible_links "
        "WHERE visible_links.track_id=t.id AND visible_links.user_id=%s)"
    ]
    parameters: list[object] = [user["id"]]
    if q.strip():
        clauses.append("(t.title ILIKE %s OR t.artist ILIKE %s OR t.album ILIKE %s OR array_to_string(t.genres, ' ') ILIKE %s)")
        parameters.extend([f"%{q.strip()}%"] * 4)
    if artist:
        clauses.append("t.artist = %s")
        parameters.append(artist)
    if album:
        clauses.append("t.album = %s")
        parameters.append(album)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with session_scope() as session:
        named_parameters = {f"p{index}": value for index, value in enumerate(parameters)}
        parameter_index = iter(named_parameters)
        named_where = where
        for name in parameter_index:
            named_where = named_where.replace("%s", f":{name}", 1)
        total = session.execute(text(f"SELECT count(*) AS total FROM tracks t {named_where}"), named_parameters).scalar_one()
        source_user_parameter = "source_user_id"
        rows = session.execute(
            text(f"""
            SELECT t.id, t.title, t.artist, t.album, t.year, t.duration_seconds,
                   t.genres, t.ingested_at,
                   (SELECT count(DISTINCT e.run_id) FROM embeddings e
                    WHERE e.track_id=t.id AND e.embedding_type='audio-track') AS embedding_runs,
                   source.external_id AS source_id, source.album_id, source.cover_art
            FROM tracks t
            LEFT JOIN LATERAL (
              SELECT ts.external_id, ts.source_data->>'albumId' AS album_id,
                     ts.source_data->>'coverArt' AS cover_art
              FROM track_sources ts
              JOIN user_track_links source_links
                ON source_links.user_id=:source_user_id AND source_links.library_id=ts.library_id
               AND source_links.track_id=ts.track_id AND source_links.external_id=ts.external_id
              WHERE ts.track_id=t.id AND ts.source_type='subsonic'
              ORDER BY ts.id LIMIT 1
            ) source ON true
            {named_where}
            ORDER BY {ordering}
            LIMIT :limit OFFSET :offset
            """),
            {**named_parameters, source_user_parameter: user["id"], "limit": limit, "offset": offset},
        ).mappings().all()
        tracks = [dict(row) for row in rows]
    return {"tracks": tracks, "total": total, "limit": limit, "offset": offset}


def _lyrics_concept_corpus(user_id: uuid.UUID) -> tuple[list[dict[str, object]], np.ndarray, str]:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT DISTINCT ON (e.track_id) t.id, t.title, t.artist, t.album,
                      e.embedding::text AS embedding, ar.id AS run_id
               FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id JOIN tracks t ON t.id=e.track_id
               WHERE e.embedding_type='lyrics' AND e.window_index IS NULL AND ar.model_name='bge_m3'
                 AND EXISTS (SELECT 1 FROM user_track_links utl
                             WHERE utl.track_id=t.id AND utl.user_id=%s)
               ORDER BY e.track_id, ar.created_at DESC""",
            (user_id,),
        )
        rows = cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="No lyrics embeddings are available")
    matrix = np.stack([np.fromstring(row.pop("embedding").strip("[]"), sep=",") for row in rows])
    run_id = str(rows[0].pop("run_id"))
    return rows, matrix, run_id


def _semantic_concept_corpus(user_id: uuid.UUID) -> tuple[list[dict[str, object]], np.ndarray, str]:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT DISTINCT ON (e.track_id) t.id, t.title, t.artist, t.album,
                   e.embedding::text AS embedding, ar.id AS run_id
            FROM embeddings e
            JOIN analysis_runs ar ON ar.id=e.run_id
            JOIN tracks t ON t.id=e.track_id
            WHERE e.embedding_type='audio-track' AND ar.model_name='muq_mulan'
              AND EXISTS (SELECT 1 FROM user_track_links utl
                          WHERE utl.track_id=t.id AND utl.user_id=%s)
            ORDER BY e.track_id, ar.created_at DESC
            """,
            (user_id,),
        )
        rows = cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="No MuQ-MuLan embeddings are available")
    matrix = np.stack([np.fromstring(row.pop("embedding").strip("[]"), sep=",") for row in rows])
    run_id = str(rows[0].pop("run_id"))
    return rows, matrix, run_id


@app.get("/library/concepts")
def library_concepts(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT id, name, description, positive_prompts, negative_prompts,
                      positive_track_ids, negative_track_ids, enabled, created_at, updated_at
               FROM concepts WHERE user_id=%s ORDER BY lower(name)""",
            (user["id"],),
        )
        personal = cursor.fetchall()
    return {"predefined": predefined_concepts(), "personal": personal}


@app.post("/library/concepts", status_code=201)
def create_concept(request: ConceptRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    if not request.positive_prompts and not request.positive_track_ids:
        raise HTTPException(status_code=422, detail="A concept needs a positive prompt or positive track")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO concepts (user_id, name, description, positive_prompts, negative_prompts,
                                  positive_track_ids, negative_track_ids)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id, name, description, positive_prompts, negative_prompts,
                      positive_track_ids, negative_track_ids, enabled, created_at, updated_at
            """,
            (user["id"], request.name.strip(), request.description.strip(), request.positive_prompts,
             request.negative_prompts, request.positive_track_ids, request.negative_track_ids),
        )
        return cursor.fetchone()


@app.post("/library/concepts/preview")
def preview_concept(request: ConceptPreviewRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    if not request.positive_prompts and not request.positive_track_ids:
        raise HTTPException(status_code=422, detail="A concept needs a positive prompt or positive track")
    rows, matrix, run_id = _semantic_concept_corpus(user["id"])
    row_index = {str(row["id"]): index for index, row in enumerate(rows)}
    def examples(identifiers: list[uuid.UUID]) -> np.ndarray | None:
        indices = [row_index[str(identifier)] for identifier in identifiers if str(identifier) in row_index]
        return matrix[indices] if indices else None
    raw, percentiles = score_concept(
        matrix, request.positive_prompts, request.negative_prompts,
        examples(request.positive_track_ids), examples(request.negative_track_ids),
    )
    ranked = np.argsort(raw)[::-1][:request.limit]
    return {
        "run_id": run_id, "corpus_size": len(rows), "calibration": "empirical-library-percentile",
        "tracks": [{**rows[index], "raw_score": float(raw[index]), "percentile": float(percentiles[index])} for index in ranked],
    }


@app.post("/library/concepts/lens")
def concept_lens(request: ConceptLensRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    requested = list(dict.fromkeys(name.strip() for name in request.concepts if name.strip()))
    definitions = {str(item["name"]).casefold(): item for item in predefined_concepts()}
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT name, positive_prompts, negative_prompts, positive_track_ids, negative_track_ids
               FROM concepts WHERE user_id=%s AND enabled""",
            (user["id"],),
        )
        for item in cursor.fetchall():
            definitions[str(item["name"]).casefold()] = item
    missing = [name for name in requested if name.casefold() not in definitions]
    if missing:
        raise HTTPException(status_code=404, detail=f"Unknown concepts: {', '.join(missing)}")
    rows, matrix, run_id = (
        _lyrics_concept_corpus(user["id"])
        if request.representation == "lyrics"
        else _semantic_concept_corpus(user["id"])
    )
    matrix = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
    lyrics_matrix: np.ndarray | None = None
    lyrics_available: np.ndarray | None = None
    if request.representation == "hybrid":
        lyrics_rows, available_lyrics, lyrics_run_id = _lyrics_concept_corpus(user["id"])
        lyrics_by_id = {str(row["id"]): available_lyrics[index] for index, row in enumerate(lyrics_rows)}
        lyrics_matrix = np.zeros((len(rows), available_lyrics.shape[1]), dtype=np.float32)
        lyrics_available = np.asarray([str(row["id"]) in lyrics_by_id for row in rows], dtype=bool)
        for index, row in enumerate(rows):
            if lyrics_available[index]:
                lyrics_matrix[index] = lyrics_by_id[str(row["id"])]
        run_id = f"{run_id}+{lyrics_run_id}"
    row_index = {str(row["id"]): index for index, row in enumerate(rows)}
    result: dict[str, list[dict[str, object]]] = {str(row["id"]): [] for row in rows}
    for name in requested:
        definition = definitions[name.casefold()]
        positive_ids = definition.get("positive_track_ids") or []
        negative_ids = definition.get("negative_track_ids") or []
        positive_indices = [row_index[str(identifier)] for identifier in positive_ids if str(identifier) in row_index]
        negative_indices = [row_index[str(identifier)] for identifier in negative_ids if str(identifier) in row_index]
        positive_prompts = definition.get("positive_prompts") or []
        negative_prompts = definition.get("negative_prompts") or []
        semantic_evidence: np.ndarray | None = None
        lyrics_evidence: np.ndarray | None = None
        if request.representation == "lyrics":
            positive_parts = list(shared_lyrics_model().embed_queries(positive_prompts)) if positive_prompts else []
            negative_parts = list(shared_lyrics_model().embed_queries(negative_prompts)) if negative_prompts else []
            positive_parts.extend(matrix[positive_indices] if positive_indices else [])
            negative_parts.extend(matrix[negative_indices] if negative_indices else [])
            if not positive_parts:
                raise HTTPException(status_code=422, detail=f"Concept {name} has no usable lyrics evidence")
            positive = np.mean(positive_parts, axis=0); positive /= max(float(np.linalg.norm(positive)), 1e-8)
            raw = matrix @ positive
            if negative_parts:
                negative = np.mean(negative_parts, axis=0); negative /= max(float(np.linalg.norm(negative)), 1e-8)
                raw -= matrix @ negative
            percentiles = empirical_percentiles(raw)
            lyrics_evidence = percentiles
        else:
            semantic_raw, percentiles = score_concept(
                matrix, positive_prompts, negative_prompts,
                matrix[positive_indices] if positive_indices else None,
                matrix[negative_indices] if negative_indices else None,
            )
            raw = semantic_raw
            semantic_evidence = empirical_percentiles(semantic_raw)
            if request.representation == "hybrid" and lyrics_matrix is not None and lyrics_available is not None:
                positive_parts = list(shared_lyrics_model().embed_queries(positive_prompts)) if positive_prompts else []
                negative_parts = list(shared_lyrics_model().embed_queries(negative_prompts)) if negative_prompts else []
                positive_parts.extend(lyrics_matrix[index] for index in positive_indices if lyrics_available[index])
                negative_parts.extend(lyrics_matrix[index] for index in negative_indices if lyrics_available[index])
                if positive_parts:
                    positive = np.mean(positive_parts, axis=0); positive /= max(float(np.linalg.norm(positive)), 1e-8)
                    lyrics_raw = lyrics_matrix @ positive
                    if negative_parts:
                        negative = np.mean(negative_parts, axis=0); negative /= max(float(np.linalg.norm(negative)), 1e-8)
                        lyrics_raw -= lyrics_matrix @ negative
                    lyrics_evidence = empirical_percentiles(lyrics_raw, lyrics_available)
                    raw, percentiles = combine_concept_percentiles(semantic_raw, lyrics_raw, lyrics_available)
        for index, row in enumerate(rows):
            if percentiles[index] >= request.minimum_percentile:
                result[str(row["id"])].append({
                    "name": name, "raw_score": float(raw[index]), "percentile": float(percentiles[index]),
                    "semantic_percentile": float(semantic_evidence[index]) if semantic_evidence is not None else None,
                    "lyrics_percentile": float(lyrics_evidence[index]) if lyrics_evidence is not None else None,
                    "lyrics_available": bool(lyrics_available[index]) if lyrics_available is not None else request.representation == "lyrics",
                })
    return {
        "run_id": run_id, "corpus_size": len(rows), "calibration": "empirical-library-percentile",
        "minimum_percentile": request.minimum_percentile, "representation": request.representation,
        "scores": result,
    }


def _curation_corpus(
    user_id: uuid.UUID, connection_id: uuid.UUID,
) -> tuple[list[dict[str, object]], np.ndarray, np.ndarray, np.ndarray]:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """WITH selected_embeddings AS (
                 SELECT DISTINCT ON (e.track_id) e.track_id, e.embedding::text AS embedding
                 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                 WHERE e.embedding_type='audio-track' AND e.window_index IS NULL AND ar.model_name='muq_mulan'
                 ORDER BY e.track_id, ar.created_at DESC
               )
               SELECT DISTINCT ON (t.id) t.id, t.title, t.artist, t.album, t.duration_seconds,
                      selected_embeddings.embedding, lyrics_embedding.embedding AS lyrics_embedding,
                      voice_embedding.embedding AS voice_embedding,
                      ts.external_id AS source_id, ts.source_data->>'coverArt' AS cover_art,
                      member.group_id::text AS recording_group_id
               FROM selected_embeddings
               JOIN tracks t ON t.id=selected_embeddings.track_id
               JOIN track_sources ts ON ts.track_id=t.id AND ts.source_type='subsonic'
               JOIN libraries l ON l.id=ts.library_id
               JOIN user_track_links ul ON ul.library_id=l.id AND ul.track_id=t.id AND ul.user_id=%s
               JOIN navidrome_connections nc ON nc.id=%s
                 AND lower(rtrim(nc.url, '/'))=lower(rtrim(l.root_path, '/'))
               LEFT JOIN recording_group_members member ON member.track_id=t.id
               LEFT JOIN LATERAL (
                 SELECT e.embedding::text AS embedding
                 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                 WHERE e.track_id=t.id AND e.embedding_type='lyrics' AND e.window_index IS NULL
                   AND ar.model_name='bge_m3'
                 ORDER BY ar.created_at DESC LIMIT 1
               ) lyrics_embedding ON true
               LEFT JOIN LATERAL (
                 SELECT e.embedding::text AS embedding
                 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                 WHERE e.track_id=t.id AND e.embedding_type='voice-gender' AND ar.model_name='mtg-jamendo-voice-gender-v2'
                 ORDER BY ar.created_at DESC LIMIT 1
               ) voice_embedding ON true
               ORDER BY t.id, ts.id""",
            (user_id, connection_id),
        )
        rows = cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="No semantic embeddings are available in this library")
    matrix = np.stack([np.fromstring(row.pop("embedding").strip("[]"), sep=",") for row in rows])
    lyrics_available = np.asarray([row.get("lyrics_embedding") is not None for row in rows], dtype=bool)
    lyrics_matrix = np.zeros((len(rows), 1024), dtype=np.float32)
    for index, row in enumerate(rows):
        encoded = row.pop("lyrics_embedding")
        if encoded is not None:
            lyrics_matrix[index] = np.fromstring(str(encoded).strip("[]"), sep=",")
    voice_available = np.asarray([row.get("voice_embedding") is not None for row in rows], dtype=bool)
    voice_matrix = np.zeros((len(rows), 3), dtype=np.float32)
    for index, row in enumerate(rows):
        encoded = row.pop("voice_embedding")
        if encoded is not None:
            voice_matrix[index] = np.fromstring(str(encoded).strip("[]"), sep=",")
    return rows, matrix, lyrics_matrix, lyrics_available, voice_matrix, voice_available


def _preview_curation(
    user_id: uuid.UUID, connection_id: uuid.UUID, request: CurationPreviewRequest,
) -> dict[str, object]:
    rows, matrix, lyrics_matrix, lyrics_available, voice_matrix, voice_available = _curation_corpus(user_id, connection_id)
    if request.curation_type == "time_of_day" and (not request.period_start or not request.period_end):
        raise HTTPException(status_code=422, detail="Choose a start and end time")
    if request.curation_type == "language" and not (
        request.positive_prompt.strip() or request.sound_prompts or request.themes_prompts
    ):
        raise HTTPException(status_code=422, detail="Add a positive direction for this language curation")
    if request.curation_type == "examples" and not request.positive_track_ids:
        raise HTTPException(status_code=422, detail="Add at least one Songs like track")
    overlap = set(request.positive_track_ids) & set(request.negative_track_ids)
    if overlap:
        raise HTTPException(status_code=422, detail="A track cannot appear in both Songs like and Songs not like")
    with session_scope() as session:
        preference = session.get(UserPreference, user_id)
        if preference is None:
            raise HTTPException(status_code=404, detail="User preferences are unavailable")
        timezone_name = preference.timezone
        lastfm_username = preference.lastfm_username
        encrypted_key = bytes(preference.lastfm_api_key_encrypted) if preference.lastfm_api_key_encrypted else None
    listen_counts: dict[str, int] | None = None
    recent_ids: set[str] | None = None
    period_counts: dict[str, int] = {}
    if lastfm_username and encrypted_key:
        try:
            api_key = _cipher().decrypt(encrypted_key).decode()
            listens = recent_listens(lastfm_username, api_key, datetime.now(timezone.utc) - timedelta(days=request.lookback_days))
            all_counts, period_counts = track_listen_counts(
                rows, listens, timezone_name,
                request.period_start if request.curation_type == "time_of_day" else None,
                request.period_end if request.curation_type == "time_of_day" else None,
            )
            listen_counts = period_counts if request.curation_type == "time_of_day" else all_counts
            recent_ids = set(all_counts)
        except Exception as error:
            raise HTTPException(status_code=502, detail=f"Could not read Last.fm listening history: {error}") from error
    elif request.curation_type == "time_of_day":
        raise HTTPException(status_code=409, detail="Connect Last.fm in Settings before creating a time-of-day curation")
    effective_positive_ids = list(request.positive_track_ids)
    if request.curation_type == "time_of_day":
        effective_positive_ids = [uuid.UUID(identifier) for identifier in period_counts]
        if not effective_positive_ids:
            raise HTTPException(status_code=409, detail="No matched listens were found in that time period during the lookback window")
    sound_tags = [tag.strip() for tag in request.sound_prompts if tag.strip()]
    theme_tags = [tag.strip() for tag in request.themes_prompts if tag.strip()]
    sound_negatives = [tag.strip() for tag in request.sound_negative_prompts if tag.strip()]
    theme_negatives = [tag.strip() for tag in request.themes_negative_prompts if tag.strip()]
    structured = bool(sound_tags or theme_tags or sound_negatives or theme_negatives)
    semantic_prompts = sound_tags if structured else ([request.positive_prompt] if request.positive_prompt.strip() else [])
    theme_prompts = theme_tags if structured else ([request.positive_prompt] if request.positive_prompt.strip() else [])
    visible_ids = {str(row["id"]) for row in rows}
    if not semantic_prompts and not theme_prompts and not any(str(value) in visible_ids for value in effective_positive_ids):
        raise HTTPException(status_code=422, detail="None of the Songs like tracks are available in this library")
    lyrics_model = shared_lyrics_model()

    def _tag_query_centers(tags: list[str]) -> list[np.ndarray]:
        centers: list[np.ndarray] = []
        for group in expand_tag_groups(tags):
            embedded = lyrics_model.embed_queries(group)
            center = np.asarray(embedded, dtype=np.float32).mean(axis=0)
            centers.append(center / max(float(np.linalg.norm(center)), 1e-8))
        return centers

    positive_queries = _tag_query_centers(theme_prompts) if theme_prompts else None
    lyrics_negatives = (theme_negatives if structured else ([request.negative_prompt] if request.negative_prompt.strip() else []))
    negative_queries = np.asarray(_tag_query_centers(lyrics_negatives), dtype=np.float32) if lyrics_negatives else None
    shuffle_seed = secrets.randbits(63)
    expanded_sound_prompts = expand_tag_groups(sound_tags) if structured and sound_tags else None
    expanded_sound_negatives = expand_tag_groups(sound_negatives) if structured and sound_negatives else None
    tracks, references = rank_curation(
        rows, matrix, request.positive_prompt, request.negative_prompt,
        request.track_limit, request.refresh_mode, [str(value) for value in request.existing_track_ids],
        [str(value) for value in effective_positive_ids],
        [str(value) for value in request.negative_track_ids],
        lyrics_matrix, lyrics_available, positive_queries, negative_queries,
        listen_counts, recent_ids, request.familiarity_percent, shuffle_seed,
        voice_matrix=voice_matrix, voice_available=voice_available,
        sound_prompts=expanded_sound_prompts,
        themes_prompts=expand_tag_groups(theme_tags) if structured and theme_tags else None,
        sound_negative_prompts=expanded_sound_negatives,
        themes_negative_prompts=expand_tag_groups(theme_negatives) if structured and theme_negatives else None,
        sound_weight=request.sound_weight if structured else None,
    )
    if structured:
        weights = {"semantic": request.sound_weight / 100.0, "lyrics": (100 - request.sound_weight) / 100.0}
    else:
        weights = {"semantic": 0.45, "lyrics": 0.55}
    return {
        "tracks": tracks, "references": references, "corpus_size": len(rows),
        "curation_type": request.curation_type,
        "model": "muq_mulan+bge_m3", "weights": weights,
        "lyrics_coverage": int(lyrics_available.sum()), "shuffle_seed": shuffle_seed,
        "familiarity": {
            "percent": request.familiarity_percent, "active": listen_counts is not None,
            "lookback_days": request.lookback_days,
            "familiar_tracks": sum(track["evidence"]["selection_pool"] == "familiar" for track in tracks),
            "discovery_tracks": sum(track["evidence"]["selection_pool"] == "discovery" for track in tracks),
            "matched_listens": sum((listen_counts or {}).values()),
        },
    }


def _refresh_curation(curation_id: uuid.UUID, user_id: uuid.UUID) -> dict[str, object]:
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT * FROM curations WHERE id=%s AND user_id=%s", (curation_id, user_id))
        curation = cursor.fetchone()
        if curation is None:
            raise HTTPException(status_code=404, detail="Curation not found")
        cursor.execute(
            """SELECT crt.track_id FROM curation_revision_tracks crt
               JOIN curation_revisions cr ON cr.id=crt.revision_id
               WHERE cr.curation_id=%s ORDER BY cr.revision_number DESC, crt.position""",
            (curation_id,),
        )
        existing = [row["track_id"] for row in cursor.fetchall()[: int(curation["track_limit"])]]
        cursor.execute("UPDATE curations SET status='refreshing', last_error=NULL, updated_at=now() WHERE id=%s", (curation_id,))
    request = CurationPreviewRequest(
        curation_type=curation["curation_type"], positive_prompt=curation["positive_prompt"], negative_prompt=curation["negative_prompt"],
        sound_prompts=curation.get("sound_prompts") or [],
        themes_prompts=curation.get("themes_prompts") or [],
        sound_negative_prompts=curation.get("sound_negative_prompts") or [],
        themes_negative_prompts=curation.get("themes_negative_prompts") or [],
        sound_weight=int(curation.get("sound_weight") or 50),
        positive_track_ids=curation["positive_track_ids"], negative_track_ids=curation["negative_track_ids"],
        familiarity_percent=curation["familiarity_percent"], period_start=curation["period_start"],
        period_end=curation["period_end"], lookback_days=curation["lookback_days"],
        track_limit=curation["track_limit"], refresh_mode=curation["refresh_mode"], existing_track_ids=existing,
    )
    try:
        result = _preview_curation(user_id, curation["navidrome_connection_id"], request)
        credentials = _load_connection(str(curation["navidrome_connection_id"]))
        if credentials is None:
            raise RuntimeError("Navidrome connection is unavailable")
        source_ids = [str(track["source_id"]) for track in result["tracks"]]
        with NavidromeClient(*credentials) as client:
            playlist_id = client.replace_playlist(
                str(curation["name"]), source_ids, curation.get("navidrome_playlist_id"),
            )
        with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
            cursor.execute("SELECT coalesce(max(revision_number), 0) + 1 AS value FROM curation_revisions WHERE curation_id=%s", (curation_id,))
            revision_number = int(cursor.fetchone()["value"])
            recipe = {
                "curation_type": request.curation_type,
                "positive_prompt": request.positive_prompt, "negative_prompt": request.negative_prompt,
                "sound_prompts": request.sound_prompts, "themes_prompts": request.themes_prompts,
                "sound_negative_prompts": request.sound_negative_prompts,
                "themes_negative_prompts": request.themes_negative_prompts,
                "sound_weight": request.sound_weight,
                "positive_track_ids": [str(value) for value in request.positive_track_ids],
                "negative_track_ids": [str(value) for value in request.negative_track_ids],
                "familiarity_percent": request.familiarity_percent,
                "period_start": request.period_start, "period_end": request.period_end,
                "lookback_days": request.lookback_days,
                "track_limit": request.track_limit, "refresh_mode": request.refresh_mode,
                "references": result["references"], "model": result["model"],
                "weights": result.get("weights"), "lyrics_coverage": result.get("lyrics_coverage"),
                "familiarity": result.get("familiarity"), "shuffle_seed": result.get("shuffle_seed"),
            }
            cursor.execute(
                """INSERT INTO curation_revisions (curation_id, revision_number, recipe)
                   VALUES (%s,%s,%s) RETURNING id""",
                (curation_id, revision_number, Jsonb(recipe)),
            )
            revision_id = cursor.fetchone()["id"]
            for position, track in enumerate(result["tracks"]):
                cursor.execute(
                    """INSERT INTO curation_revision_tracks
                       (revision_id, position, track_id, score, evidence, source_id)
                       VALUES (%s,%s,%s,%s,%s,%s)""",
                    (revision_id, position, track["id"], track["score"],
                     Jsonb({"percentile": track["percentile"], "retained": track["retained"], **track.get("evidence", {})}), track["source_id"]),
                )
            cursor.execute(
                """UPDATE curations SET navidrome_playlist_id=%s, status='ready', last_error=NULL,
                   last_refreshed_at=now(), next_refresh_at=CASE WHEN refresh_enabled THEN now() + interval '6 hours' END,
                   updated_at=now() WHERE id=%s""",
                (playlist_id, curation_id),
            )
        return {**result, "id": str(curation_id), "playlist_id": playlist_id, "revision_number": revision_number}
    except Exception as error:
        with psycopg.connect(os.environ["DATABASE_URL"]) as connection, connection.cursor() as cursor:
            cursor.execute("UPDATE curations SET status='failed', last_error=%s, updated_at=now() WHERE id=%s", (str(error), curation_id))
        raise


@app.post("/library/curations/preview")
def preview_curation(request: CurationPreviewRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    connection_id = user.get("navidrome_connection_id")
    if connection_id is None:
        raise HTTPException(status_code=409, detail="No Navidrome connection is configured")
    return _preview_curation(user["id"], connection_id, request)


@app.get("/library/curations")
def list_curations(echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT c.*, latest.recipe,
                   coalesce((SELECT jsonb_agg(jsonb_build_object('id', pt.id, 'title', pt.title, 'artist', pt.artist, 'album', pt.album)) FROM tracks pt WHERE pt.id=ANY(c.positive_track_ids)), '[]') AS positive_tracks,
                   coalesce((SELECT jsonb_agg(jsonb_build_object('id', nt.id, 'title', nt.title, 'artist', nt.artist, 'album', nt.album)) FROM tracks nt WHERE nt.id=ANY(c.negative_track_ids)), '[]') AS negative_tracks,
                   coalesce(jsonb_agg(jsonb_build_object(
                     'id', t.id, 'title', t.title, 'artist', t.artist, 'album', t.album,
                     'duration_seconds', t.duration_seconds, 'source_id', crt.source_id,
                     'position', crt.position, 'score', crt.score,
                     'percentile', nullif(crt.evidence->>'percentile','')::real,
                     'retained', coalesce((crt.evidence->>'retained')::boolean, false),
                     'evidence', crt.evidence,
                     'cover_art', (
                       SELECT max(ts.source_data->>'coverArt')
                       FROM user_track_links utl
                       JOIN track_sources ts ON ts.library_id=utl.library_id
                                             AND ts.track_id=utl.track_id
                                             AND ts.external_id=crt.source_id
                       WHERE utl.user_id=c.user_id AND utl.track_id=crt.track_id
                     )
                   ) ORDER BY crt.position) FILTER (WHERE crt.track_id IS NOT NULL), '[]') AS tracks
               FROM curations c
               LEFT JOIN LATERAL (
                 SELECT id, recipe FROM curation_revisions
                 WHERE curation_id=c.id ORDER BY revision_number DESC LIMIT 1
               ) latest ON true
               LEFT JOIN curation_revision_tracks crt ON crt.revision_id=latest.id
               LEFT JOIN tracks t ON t.id=crt.track_id
               WHERE c.user_id=%s GROUP BY c.id, latest.recipe ORDER BY c.updated_at DESC""",
            (user["id"],),
        )
        return {"curations": cursor.fetchall()}


@app.post("/library/curations", status_code=201)
def create_curation(request: CurationCreateRequest, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    connection_id = user.get("navidrome_connection_id")
    if connection_id is None:
        raise HTTPException(status_code=409, detail="No Navidrome connection is configured")
    with session_scope() as session:
        curation = Curation(
            user_id=user["id"], navidrome_connection_id=connection_id, name=request.name.strip(),
            curation_type=request.curation_type,
            positive_prompt=request.positive_prompt.strip(), negative_prompt=request.negative_prompt.strip(),
            sound_prompts=request.sound_prompts, themes_prompts=request.themes_prompts,
            sound_negative_prompts=request.sound_negative_prompts,
            themes_negative_prompts=request.themes_negative_prompts,
            sound_weight=request.sound_weight,
            positive_track_ids=request.positive_track_ids, negative_track_ids=request.negative_track_ids,
            familiarity_percent=request.familiarity_percent, period_start=request.period_start,
            period_end=request.period_end, lookback_days=request.lookback_days,
            track_limit=request.track_limit, refresh_mode=request.refresh_mode,
            refresh_enabled=request.refresh_enabled,
        )
        session.add(curation)
        session.flush()
        curation_id = curation.id
    return _refresh_curation(curation_id, user["id"])


@app.patch("/library/curations/{curation_id}")
def update_curation(
    curation_id: uuid.UUID, request: CurationUpdateRequest,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    values = request.model_dump(exclude_none=True)
    if not values:
        return {"id": str(curation_id)}
    with session_scope() as session:
        curation = session.scalar(select(Curation).where(Curation.id == curation_id, Curation.user_id == user["id"]))
        if curation is None:
            raise HTTPException(status_code=404, detail="Curation not found")
        for key, value in values.items():
            setattr(curation, key, value)
        if "refresh_enabled" in values:
            curation.next_refresh_at = datetime.now(timezone.utc) + timedelta(hours=6) if values["refresh_enabled"] else None
        curation.updated_at = datetime.now(timezone.utc)
    return {"id": str(curation_id), **values}


@app.post("/library/curations/{curation_id}/refresh")
def refresh_curation(curation_id: uuid.UUID, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    user = _session_user(echora_session)
    return _refresh_curation(curation_id, user["id"])


@app.delete("/library/curations/{curation_id}", status_code=204)
def delete_curation(
    curation_id: uuid.UUID, delete_navidrome: bool = True,
    echora_session: str | None = Cookie(default=None),
) -> Response:
    user = _session_user(echora_session)
    with session_scope() as session:
        curation = session.scalar(select(Curation).where(Curation.id == curation_id, Curation.user_id == user["id"]))
        if curation is None:
            raise HTTPException(status_code=404, detail="Curation not found")
        connection_id, playlist_id = curation.navidrome_connection_id, curation.navidrome_playlist_id

    # Delete remotely first so a Navidrome failure does not leave an orphaned
    # playlist after Echora has already forgotten its ID.
    if delete_navidrome and playlist_id:
        credentials = _load_connection(str(connection_id))
        if credentials is None:
            raise HTTPException(status_code=409, detail="Navidrome connection is unavailable; keep the Navidrome playlist or reconnect the server")
        with NavidromeClient(*credentials) as client:
            client.delete_playlist(str(playlist_id))

    with session_scope() as session:
        curation = session.scalar(select(Curation).where(Curation.id == curation_id, Curation.user_id == user["id"]))
        if curation is not None:
            session.delete(curation)
    return Response(status_code=204)


def _curation_scheduler() -> None:
    while True:
        try:
            with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
                cursor.execute(
                    """SELECT id, user_id FROM curations
                       WHERE refresh_enabled AND status <> 'refreshing' AND next_refresh_at <= now()
                       ORDER BY next_refresh_at LIMIT 10"""
                )
                due = cursor.fetchall()
            for item in due:
                try:
                    _refresh_curation(item["id"], item["user_id"])
                except Exception:
                    logger.exception("Scheduled curation refresh failed for %s", item["id"])
        except Exception:
            logger.exception("Curation scheduler failed")
        threading.Event().wait(60)


def _cluster_embeddings(normalized: np.ndarray, similarities: np.ndarray) -> tuple[np.ndarray, dict[str, object]]:
    count = len(normalized)
    if count < 3:
        return np.zeros(count, dtype=int), {"algorithm": "SNN-Leiden", "clusters": 1, "neighbors": max(0, count - 1)}
    neighbor_count = min(count - 1, max(5, round(np.sqrt(count))))
    nearest = np.argsort(similarities, axis=1)[:, -(neighbor_count + 1):-1]
    neighbor_sets = [set(map(int, row)) for row in nearest]
    edge_weights: dict[tuple[int, int], float] = {}
    for left in range(count):
        for right_value in nearest[left]:
            right = int(right_value)
            edge = (min(left, right), max(left, right))
            shared = len(neighbor_sets[left] & neighbor_sets[right])
            weight = max(0.01, shared / neighbor_count) * max(0.01, float(similarities[left, right]))
            edge_weights[edge] = max(edge_weights.get(edge, 0.0), weight)
    graph = ig.Graph(n=count, edges=list(edge_weights), directed=False)
    weights = list(edge_weights.values())
    resolutions = [0.4, 0.55, 0.7, 0.85, 1.0, 1.2, 1.45, 1.75]
    candidates: list[dict[str, object]] = []
    for resolution in resolutions:
        runs: list[tuple[np.ndarray, float]] = []
        for seed in range(6):
            ig.set_random_number_generator(random.Random(104729 + seed))
            partition = graph.community_leiden(
                objective_function="modularity", weights=weights, resolution=resolution, n_iterations=-1,
            )
            runs.append((np.asarray(partition.membership, dtype=int), float(partition.quality)))
        best_labels, quality = max(runs, key=lambda item: item[1])
        comparisons = [adjusted_rand_score(runs[left][0], runs[right][0]) for left in range(len(runs)) for right in range(left + 1, len(runs))]
        stability = float(np.mean(comparisons)) if comparisons else 1.0
        clusters = len(np.unique(best_labels))
        silhouette = float(silhouette_score(normalized, best_labels, metric="cosine")) if 1 < clusters < count else -1.0
        candidates.append({"resolution": resolution, "labels": best_labels, "clusters": clusters, "silhouette": silhouette, "stability": stability})
    has_multiple = any(int(candidate["clusters"]) > 1 for candidate in candidates)
    for index, candidate in enumerate(candidates):
        plateau = sum(index + offset in range(len(candidates)) and candidates[index + offset]["clusters"] == candidate["clusters"] for offset in (-1, 1))
        candidate["score"] = float(candidate["silhouette"]) + 0.35 * float(candidate["stability"]) + 0.1 * plateau
        if has_multiple and int(candidate["clusters"]) == 1:
            candidate["score"] = -10.0
    selected = max(candidates, key=lambda candidate: float(candidate["score"]))
    labels = np.asarray(selected["labels"], dtype=int)
    ordered = sorted(np.unique(labels), key=lambda label: (-int(np.sum(labels == label)), int(label)))
    remap = {old: new for new, old in enumerate(ordered)}
    labels = np.asarray([remap[int(label)] for label in labels], dtype=int)
    return labels, {
        "algorithm": "SNN-Leiden", "clusters": len(ordered), "neighbors": neighbor_count,
        "resolution": selected["resolution"], "silhouette": selected["silhouette"],
        "seed_stability_ari": selected["stability"], "resolutions_tested": resolutions,
    }


@app.get("/library/map")
def library_map(
    model: str = "muq_mulan", limit: int = 1500, semantic_weight: float | None = None,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    limit = min(max(limit, 10), 3000)
    if model not in {"muq_mulan", "mert", "lyrics", "blend"}:
        raise HTTPException(status_code=422, detail="Unknown representation")
    if model == "blend":
        semantic_weight = 0.5 if semantic_weight is None else semantic_weight
        if not 0 <= semantic_weight <= 1:
            raise HTTPException(status_code=422, detail="semantic_weight must be between 0 and 1")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        if model == "blend":
            cursor.execute(
                """
                WITH semantic AS (
                  SELECT DISTINCT ON (e.track_id) e.track_id, e.embedding::text AS embedding,
                         ar.id AS run_id, ar.model_revision, ar.created_at
                  FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                  WHERE e.embedding_type='audio-track' AND ar.model_name='muq_mulan'
                  ORDER BY e.track_id, ar.created_at DESC
                ), acoustic AS (
                  SELECT DISTINCT ON (e.track_id) e.track_id, e.embedding::text AS embedding,
                         ar.id AS run_id, ar.model_revision, ar.created_at
                  FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                  WHERE e.embedding_type='audio-track' AND ar.model_name='mert'
                  ORDER BY e.track_id, ar.created_at DESC
                )
                SELECT t.id, t.title, t.artist, t.album, t.duration_seconds, t.genres,
                       semantic.embedding AS semantic_embedding, acoustic.embedding AS acoustic_embedding,
                       semantic.run_id::text || ':' || acoustic.run_id::text AS run_id,
                       semantic.model_revision || ':' || acoustic.model_revision AS model_revision,
                       greatest(semantic.created_at, acoustic.created_at) AS run_created_at,
                       max(ts.external_id) AS source_id, max(ts.source_data->>'coverArt') AS cover_art
                FROM semantic JOIN acoustic USING (track_id) JOIN tracks t ON t.id=semantic.track_id
                LEFT JOIN track_sources ts ON ts.track_id=t.id
                  AND EXISTS (SELECT 1 FROM user_track_links source_links
                              WHERE source_links.user_id=%s AND source_links.library_id=ts.library_id
                                AND source_links.track_id=ts.track_id AND source_links.external_id=ts.external_id)
                WHERE EXISTS (SELECT 1 FROM user_track_links visible_links
                              WHERE visible_links.track_id=t.id AND visible_links.user_id=%s)
                GROUP BY t.id, semantic.embedding, acoustic.embedding, semantic.run_id, acoustic.run_id,
                         semantic.model_revision, acoustic.model_revision, semantic.created_at, acoustic.created_at
                ORDER BY t.id LIMIT %s
                """,
                (user["id"], user["id"], limit),
            )
        else:
            cursor.execute(
                """
                WITH selected_embeddings AS (
                  SELECT DISTINCT ON (e.track_id) e.track_id, e.embedding::text AS embedding,
                         ar.id AS run_id, ar.model_revision, ar.created_at AS run_created_at
                  FROM embeddings e JOIN analysis_runs ar ON ar.id = e.run_id
                  WHERE e.embedding_type = %s AND ar.model_name = %s AND e.window_index IS NULL
                  ORDER BY e.track_id, ar.created_at DESC
                )
                SELECT t.id, t.title, t.artist, t.album, t.duration_seconds, t.genres,
                       selected_embeddings.embedding, selected_embeddings.run_id,
                       selected_embeddings.model_revision, selected_embeddings.run_created_at,
                       max(ts.external_id) AS source_id, max(ts.source_data->>'coverArt') AS cover_art
                FROM selected_embeddings JOIN tracks t ON t.id = selected_embeddings.track_id
                LEFT JOIN track_sources ts ON ts.track_id = t.id
                  AND EXISTS (SELECT 1 FROM user_track_links source_links
                              WHERE source_links.user_id=%s AND source_links.library_id=ts.library_id
                                AND source_links.track_id=ts.track_id AND source_links.external_id=ts.external_id)
                WHERE EXISTS (SELECT 1 FROM user_track_links visible_links
                              WHERE visible_links.track_id=t.id AND visible_links.user_id=%s)
                GROUP BY t.id, selected_embeddings.embedding, selected_embeddings.run_id,
                         selected_embeddings.model_revision, selected_embeddings.run_created_at
                ORDER BY t.id LIMIT %s
                """,
                (
                    "lyrics" if model == "lyrics" else "audio-track",
                    "bge_m3" if model == "lyrics" else model,
                    user["id"], user["id"], limit,
                ),
            )
        rows = cursor.fetchall()
    if not rows:
        return {"points": [], "model": model}
    if model == "blend":
        semantic = np.stack([np.fromstring(row.pop("semantic_embedding").strip("[]"), sep=",") for row in rows])
        acoustic = np.stack([np.fromstring(row.pop("acoustic_embedding").strip("[]"), sep=",") for row in rows])
        semantic /= np.maximum(np.linalg.norm(semantic, axis=1, keepdims=True), 1e-8)
        acoustic /= np.maximum(np.linalg.norm(acoustic, axis=1, keepdims=True), 1e-8)
        matrix = np.concatenate([np.sqrt(semantic_weight) * semantic, np.sqrt(1 - semantic_weight) * acoustic], axis=1)
    else:
        matrix = np.stack([np.fromstring(row.pop("embedding").strip("[]"), sep=",") for row in rows])
    effective_weight = float(semantic_weight if model == "blend" else (1 if model == "muq_mulan" else 0))
    corpus_material = "|".join(
        [model, f"{effective_weight:.4f}", str(_COMMUNITY_SNAPSHOT_REVISION), *[f"{row['id']}:{row['run_id']}" for row in rows]]
    )
    corpus_hash = hashlib.sha256(corpus_material.encode()).hexdigest()
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT id, payload, created_at FROM community_snapshots
               WHERE model_name=%s AND semantic_weight=%s AND corpus_hash=%s AND algorithm_revision=%s""",
            (model, effective_weight, corpus_hash, _COMMUNITY_SNAPSHOT_REVISION),
        )
        cached = cursor.fetchone()
    if cached:
        payload = dict(cached["payload"])
        payload["snapshot_id"] = str(cached["id"])
        payload["snapshot_created_at"] = cached["created_at"]
        payload["cache_hit"] = True
        return payload
    normalized = matrix / np.maximum(np.linalg.norm(matrix, axis=1, keepdims=True), 1e-8)
    similarities = normalized @ normalized.T
    centered = normalized - normalized.mean(axis=0, keepdims=True)
    left_vectors, singular_values, _ = np.linalg.svd(centered, full_matrices=False)
    projection = left_vectors[:, :2] * singular_values[:2]
    scale = np.percentile(np.abs(projection), 97, axis=0)
    projection = projection / np.maximum(scale, 1e-6)
    labels, clustering = _cluster_embeddings(normalized, similarities)
    cluster_count = len(np.unique(labels))
    embedding_centers = np.stack([normalized[labels == index].mean(axis=0) for index in range(cluster_count)])
    embedding_centers /= np.maximum(np.linalg.norm(embedding_centers, axis=1, keepdims=True), 1e-8)
    membership_logits = normalized @ embedding_centers.T / 0.08
    membership_logits -= membership_logits.max(axis=1, keepdims=True)
    memberships = np.exp(membership_logits)
    memberships /= memberships.sum(axis=1, keepdims=True)
    if cluster_count:
        center_matrix = np.stack([projection[labels == index].mean(axis=0) for index in range(cluster_count)])
        layout_centers = center_matrix.copy()
        for _ in range(80):
            for left in range(cluster_count):
                for right in range(left + 1, cluster_count):
                    delta = layout_centers[right] - layout_centers[left]
                    distance = float(np.linalg.norm(delta))
                    if distance < 0.9:
                        if distance < 1e-6:
                            angle = (left * 2.399963 + right) % (2 * np.pi)
                            delta = np.array([np.cos(angle), np.sin(angle)])
                            distance = 1.0
                        shift = delta / distance * (0.9 - distance) * 0.08
                        layout_centers[left] -= shift
                        layout_centers[right] += shift
        packed = projection.copy()
        clustered = labels >= 0
        packed[clustered] = layout_centers[labels[clustered]] + (projection[clustered] - center_matrix[labels[clustered]]) * 0.34
        projection = packed
    projection -= projection.mean(axis=0, keepdims=True)
    packed_scale = np.percentile(np.abs(projection), 97, axis=0)
    projection /= np.maximum(packed_scale, 1e-6)
    center_matrix = np.stack([projection[labels == index].mean(axis=0) for index in range(cluster_count)]) if cluster_count else np.empty((0, 2))
    communities = []
    for cluster in range(cluster_count):
        member_indices = np.flatnonzero(labels == cluster)
        genres = Counter(genre for item in member_indices for genre in (rows[item].get("genres") or []) if genre)
        top_genres = [{"name": name, "tracks": count} for name, count in genres.most_common(3)]
        representatives = sorted(member_indices, key=lambda item: float(normalized[item] @ embedding_centers[cluster]), reverse=True)[:3]
        label_parts = [item["name"] for item in top_genres[:2]]
        label = " / ".join(label_parts) if label_parts else f"Community {cluster + 1}"
        cohesion = float(np.mean(normalized[member_indices] @ embedding_centers[cluster]))
        communities.append({
            "id": cluster, "label": label, "x": float(center_matrix[cluster, 0]),
            "y": float(center_matrix[cluster, 1]), "size": len(member_indices), "cohesion": cohesion,
            "top_genres": top_genres,
            "representative_tracks": [{"id": str(rows[item]["id"]), "title": rows[item]["title"], "artist": rows[item].get("artist")} for item in representatives],
        })
    nearest_count = min(6, max(0, len(rows) - 1))
    nearest_sets = [set(map(int, np.argsort(similarities[index])[::-1][1:nearest_count + 1])) for index in range(len(rows))]
    edge_map: dict[tuple[int, int], dict[str, object]] = {}
    for left, neighbors_for_left in enumerate(nearest_sets):
        for right in neighbors_for_left:
            edge = (min(left, right), max(left, right))
            edge_map[edge] = {
                "source_id": str(rows[edge[0]]["id"]), "target_id": str(rows[edge[1]]["id"]),
                "similarity": float(similarities[edge[0], edge[1]]),
                "mutual": left in nearest_sets[right], "cross_community": bool(labels[edge[0]] != labels[edge[1]]),
            }
    provenance = {
        "run_id": str(rows[0]["run_id"]), "model_revision": rows[0].get("model_revision"),
        "run_created_at": rows[0].get("run_created_at"), "track_count": len(rows),
    }
    points = []
    for index, row in enumerate(rows):
        cluster = int(labels[index])
        affinity = float(memberships[index, cluster])
        entropy = float(-np.sum(memberships[index] * np.log(np.maximum(memberships[index], 1e-12))))
        bridge_score = entropy / max(np.log(cluster_count), 1e-8) if cluster_count > 1 else 0.0
        strongest = np.argsort(memberships[index])[::-1][:3]
        cluster_memberships = [{"cluster": int(value), "strength": float(memberships[index, value])} for value in strongest]
        nearest = np.argsort(similarities[index])[::-1]
        neighbors = [{"id": str(rows[item]["id"]), "title": rows[item]["title"], "artist": rows[item]["artist"], "similarity": float(similarities[index, item])} for item in nearest if item != index][:4]
        public_row = {key: value for key, value in row.items() if key not in {"run_id", "model_revision", "run_created_at"}}
        points.append({**public_row, "x": float(projection[index, 0]), "y": float(projection[index, 1]), "cluster": cluster, "cluster_affinity": affinity, "cluster_memberships": cluster_memberships, "bridge_score": bridge_score, "neighbors": neighbors})
    payload = jsonable_encoder({
        "points": points, "clusters": communities, "communities": communities,
        "edges": list(edge_map.values()), "model": model, "semantic_weight": effective_weight,
        "clustering": {**clustering, **provenance}, "corpus_hash": corpus_hash,
    })
    parameters = {
        "algorithm": clustering["algorithm"], "algorithm_revision": _COMMUNITY_SNAPSHOT_REVISION,
        "neighbors": clustering["neighbors"], "resolution": clustering["resolution"],
        "resolutions_tested": clustering["resolutions_tested"], "semantic_weight": effective_weight,
    }
    metrics = {"silhouette": clustering["silhouette"], "seed_stability_ari": clustering["seed_stability_ari"]}
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO community_snapshots
                 (model_name, semantic_weight, corpus_hash, algorithm_revision, track_count, parameters, metrics, payload)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (model_name, semantic_weight, corpus_hash, algorithm_revision)
               DO UPDATE SET payload=EXCLUDED.payload, parameters=EXCLUDED.parameters, metrics=EXCLUDED.metrics
               RETURNING id, created_at""",
            (model, effective_weight, corpus_hash, _COMMUNITY_SNAPSHOT_REVISION, len(rows),
             Jsonb(parameters), Jsonb(metrics), Jsonb(payload)),
        )
        snapshot = cursor.fetchone()
    return {**payload, "snapshot_id": str(snapshot["id"]), "snapshot_created_at": snapshot["created_at"], "cache_hit": False}


@app.get("/library/community-snapshots", dependencies=[Depends(require_user)])
def community_snapshots(
    limit: int = 20, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _session_user(echora_session)
    limit = min(max(limit, 1), 100)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT id, model_name, semantic_weight, corpus_hash, algorithm_revision,
                      track_count, parameters, metrics, created_at
               FROM community_snapshots ORDER BY created_at DESC LIMIT %s""",
            (limit,),
        )
        snapshots = cursor.fetchall()
    return {"snapshots": snapshots}


@app.get("/library/community-snapshots/{snapshot_id}", dependencies=[Depends(require_user)])
def community_snapshot(
    snapshot_id: uuid.UUID, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _session_user(echora_session)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute("SELECT payload, created_at FROM community_snapshots WHERE id=%s", (snapshot_id,))
        snapshot = cursor.fetchone()
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Community snapshot not found")
    return {**snapshot["payload"], "snapshot_id": str(snapshot_id), "snapshot_created_at": snapshot["created_at"], "cache_hit": True}


def _artist_embedding_corpus(model: str) -> tuple[list[dict[str, object]], np.ndarray, str]:
    if model not in {"muq_mulan", "mert"}:
        raise HTTPException(status_code=422, detail="Artist profiles support muq_mulan or mert")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT DISTINCT ON (e.track_id) t.id, t.title, t.artist, t.album,
                      e.embedding::text AS embedding, ar.id AS run_id
               FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id JOIN tracks t ON t.id=e.track_id
               WHERE e.embedding_type='audio-track' AND ar.model_name=%s AND t.artist IS NOT NULL
               ORDER BY e.track_id, ar.created_at DESC""",
            (model,),
        )
        rows = cursor.fetchall()
    if not rows:
        raise HTTPException(status_code=409, detail="No artist embeddings are available")
    matrix = np.stack([np.fromstring(row.pop("embedding").strip("[]"), sep=",") for row in rows])
    corpus_hash = hashlib.sha256("|".join(f"{row['id']}:{row['run_id']}" for row in rows).encode()).hexdigest()
    for row in rows:
        row.pop("run_id", None)
    return rows, matrix, corpus_hash


def _artist_payload(name: str, rows: list[dict[str, object]], matrix: np.ndarray, indices: list[int]) -> tuple[dict[str, object], object]:
    artist_matrix = matrix[indices]
    profile = fit_artist_profile(artist_matrix)
    representatives = representative_indices(artist_matrix, profile)
    facets = []
    for component, representative in enumerate(representatives):
        members = np.flatnonzero(profile.component_labels == component)
        track = rows[indices[representative]]
        facets.append({
            "index": component, "weight": float(profile.weights[component]), "track_count": int(len(members)),
            "representative_track": {"id": str(track["id"]), "title": track["title"], "artist": track["artist"], "album": track["album"]},
        })
    return {"artist": name, "track_count": len(indices), "component_count": len(profile.weights), "facets": facets}, profile


@app.get("/library/artists/profile", dependencies=[Depends(require_user)])
def artist_profile(
    artist: str, model: str = "muq_mulan", echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _session_user(echora_session)
    rows, matrix, corpus_hash = _artist_embedding_corpus(model)
    indices = [index for index, row in enumerate(rows) if str(row["artist"]).casefold() == artist.casefold()]
    if not indices:
        raise HTTPException(status_code=404, detail="Artist not found")
    display_name = str(rows[indices[0]]["artist"])
    payload, profile = _artist_payload(display_name, rows, matrix, indices)
    stored = jsonable_encoder({**payload, "model": model, "corpus_hash": corpus_hash})
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """INSERT INTO artist_profiles
                 (artist_key, artist_name, model_name, corpus_hash, track_count, component_count, payload)
               VALUES (%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (artist_key, model_name, corpus_hash) DO UPDATE SET payload=EXCLUDED.payload
               RETURNING id, created_at""",
            (display_name.casefold(), display_name, model, corpus_hash, len(indices), len(profile.weights), Jsonb(stored)),
        )
        saved = cursor.fetchone()
    return {**stored, "profile_id": str(saved["id"]), "created_at": saved["created_at"]}


@app.get("/library/artists/similar", dependencies=[Depends(require_user)])
def similar_artists(
    artist: str, model: str = "muq_mulan", limit: int = 12,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _session_user(echora_session)
    limit = min(max(limit, 1), 30)
    rows, matrix, _ = _artist_embedding_corpus(model)
    groups: dict[str, list[int]] = {}
    names: dict[str, str] = {}
    for index, row in enumerate(rows):
        key = str(row["artist"]).casefold()
        groups.setdefault(key, []).append(index)
        names.setdefault(key, str(row["artist"]))
    target_key = artist.casefold()
    if target_key not in groups:
        raise HTTPException(status_code=404, detail="Artist not found")
    _, target = _artist_payload(names[target_key], rows, matrix, groups[target_key])
    target_center = weighted_center(target)
    centroid_candidates = []
    for key, indices in groups.items():
        if key == target_key:
            continue
        center = np.mean(matrix[indices], axis=0)
        center /= max(float(np.linalg.norm(center)), 1e-8)
        centroid_candidates.append((key, float(target_center @ center)))
    candidates = sorted(centroid_candidates, key=lambda item: item[1], reverse=True)[:max(limit * 3, 30)]
    results = []
    for key, coarse_similarity in candidates:
        payload, profile = _artist_payload(names[key], rows, matrix, groups[key])
        similarity, forward, backward, component_matrix = soft_chamfer_similarity(target, profile)
        target_component, candidate_component = np.unravel_index(np.argmax(component_matrix), component_matrix.shape)
        results.append({
            **payload, "similarity": similarity, "target_coverage": forward, "candidate_coverage": backward,
            "coarse_similarity": coarse_similarity,
            "strongest_facet_match": {"target_facet": int(target_component), "candidate_facet": int(candidate_component),
                                      "similarity": float(component_matrix[target_component, candidate_component])},
        })
    results.sort(key=lambda item: float(item["similarity"]), reverse=True)
    return {"artist": names[target_key], "model": model, "results": results[:limit]}


@app.post("/library/journeys/preview", dependencies=[Depends(require_user)])
def preview_journey(
    request: JourneyRequest, echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    _session_user(echora_session)
    if request.start_track_id == request.end_track_id:
        raise HTTPException(status_code=422, detail="Journey endpoints must be different tracks")
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """
            WITH semantic AS (
              SELECT DISTINCT ON (e.track_id) e.track_id, e.embedding::text AS embedding
              FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
              WHERE e.embedding_type='audio-track' AND ar.model_name='muq_mulan'
              ORDER BY e.track_id, ar.created_at DESC
            ), acoustic AS (
              SELECT DISTINCT ON (e.track_id) e.track_id, e.embedding::text AS embedding
              FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
              WHERE e.embedding_type='audio-track' AND ar.model_name='mert'
              ORDER BY e.track_id, ar.created_at DESC
            )
            SELECT t.id, t.title, t.artist, t.album, t.duration_seconds,
                   semantic.embedding AS semantic_embedding, acoustic.embedding AS acoustic_embedding,
                   max(ts.external_id) AS source_id, max(ts.source_data->>'coverArt') AS cover_art,
                   max(member.group_id::text) AS recording_group_id
            FROM tracks t JOIN semantic ON semantic.track_id=t.id JOIN acoustic ON acoustic.track_id=t.id
            LEFT JOIN track_sources ts ON ts.track_id=t.id
            LEFT JOIN recording_group_members member ON member.track_id=t.id
            GROUP BY t.id, semantic.embedding, acoustic.embedding ORDER BY t.id
            """
        )
        rows = cursor.fetchall()
    identifiers = {str(row["id"]): index for index, row in enumerate(rows)}
    start_index, end_index = identifiers.get(str(request.start_track_id)), identifiers.get(str(request.end_track_id))
    if start_index is None or end_index is None:
        raise HTTPException(status_code=404, detail="One or both journey endpoints lack required embeddings")
    start_group = rows[start_index].get("recording_group_id")
    if start_group and start_group == rows[end_index].get("recording_group_id"):
        raise HTTPException(
            status_code=422, detail="Journey endpoints must be different recordings",
        )
    semantic = normalize_journey_rows(np.stack([np.fromstring(row.pop("semantic_embedding").strip("[]"), sep=",") for row in rows]))
    acoustic = normalize_journey_rows(np.stack([np.fromstring(row.pop("acoustic_embedding").strip("[]"), sep=",") for row in rows]))
    if request.mode == "semantic":
        matrix = semantic
        semantic_weight = 1.0
    elif request.mode == "acoustic":
        matrix = acoustic
        semantic_weight = 0.0
    else:
        semantic_weight = request.semantic_weight
        matrix = np.concatenate([np.sqrt(semantic_weight) * semantic, np.sqrt(1 - semantic_weight) * acoustic], axis=1)
    targets = spherical_targets(matrix[start_index], matrix[end_index], request.length)
    selected = select_journey(
        matrix, targets, start_index, end_index,
        [row.get("artist") for row in rows], [row.get("recording_group_id") for row in rows],
    )
    steps = []
    for position, (index, target_similarity, transition_similarity) in enumerate(selected):
        row = rows[index]
        steps.append({
            **row, "position": position, "target_progress": position / max(len(selected) - 1, 1),
            "target_similarity": target_similarity, "transition_similarity": transition_similarity,
        })
    return {"mode": request.mode, "semantic_weight": semantic_weight, "requested_length": request.length, "steps": steps}


@app.get("/library/facets")
def library_facets(
    artist_query: str = "", album_query: str = "", artist: str = "", limit: int = 20,
    echora_session: str | None = Cookie(default=None),
) -> dict[str, object]:
    user = _session_user(echora_session)
    limit = min(max(limit, 1), 50)
    with psycopg.connect(os.environ["DATABASE_URL"], row_factory=dict_row) as connection, connection.cursor() as cursor:
        cursor.execute(
            """SELECT artist AS name, count(*) AS tracks FROM tracks t
               WHERE artist IS NOT NULL AND artist ILIKE %s
                 AND EXISTS (SELECT 1 FROM user_track_links utl
                             WHERE utl.track_id=t.id AND utl.user_id=%s)
               GROUP BY artist ORDER BY artist LIMIT %s""",
            (f"%{artist_query.strip()}%", user["id"], limit),
        )
        artists = cursor.fetchall()
        album_clauses = [
            "album IS NOT NULL", "album ILIKE %s",
            "EXISTS (SELECT 1 FROM user_track_links utl WHERE utl.track_id=t.id AND utl.user_id=%s)",
        ]
        album_parameters: list[object] = [f"%{album_query.strip()}%", user["id"]]
        if artist:
            album_clauses.append("artist = %s")
            album_parameters.append(artist)
        cursor.execute(
            f"SELECT album AS name, count(*) AS tracks FROM tracks t WHERE {' AND '.join(album_clauses)} GROUP BY album ORDER BY album LIMIT %s",
            [*album_parameters, limit],
        )
        albums = cursor.fetchall()
    return {"artists": artists, "albums": albums}


@app.get("/jobs/{job_id}", dependencies=[Depends(require_user)])
def job(job_id: str, echora_session: str | None = Cookie(default=None)) -> dict[str, object]:
    _session_user(echora_session)
    with _jobs_lock:
        value = _jobs.get(job_id)
    if value is None:
        raise HTTPException(status_code=404, detail="Job not found")
    public = {key: value[key] for key in value if key != "error" and not key.startswith("_")}
    return {"job_id": job_id, **public}
