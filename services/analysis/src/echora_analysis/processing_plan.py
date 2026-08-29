from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Iterable

import psycopg


@dataclass(frozen=True)
class ProcessingPlan:
    lyrics_external_ids: tuple[str, ...] = ()
    karaoke_external_ids: tuple[str, ...] = ()

    @property
    def needs_bge(self) -> bool:
        return bool(self.lyrics_external_ids)

    @property
    def needs_fa_kara(self) -> bool:
        return bool(self.karaoke_external_ids)

    @property
    def empty(self) -> bool:
        return not self.needs_bge and not self.needs_fa_kara


@dataclass(frozen=True)
class AudioProcessingPlan:
    muq_external_ids: frozenset[str]
    mert_external_ids: frozenset[str]
    fingerprint_external_ids: frozenset[str]
    melody_external_ids: frozenset[str]

    @property
    def needs_muq(self) -> bool:
        return bool(self.muq_external_ids)

    @property
    def needs_mert(self) -> bool:
        return bool(self.mert_external_ids)

    @property
    @property
    def needs_melody(self) -> bool:
        return bool(self.melody_external_ids)

    @property
    def download_external_ids(self) -> frozenset[str]:
        return self.muq_external_ids | self.mert_external_ids | self.fingerprint_external_ids | self.melody_external_ids


def _id_filter(external_ids: Iterable[str] | None) -> tuple[str, list[object]]:
    if external_ids is None:
        return "", []
    values = list(external_ids)
    return " AND ts.external_id=ANY(%s)", [values]


def plan_lyrics(connection: psycopg.Connection, external_ids: Iterable[str] | None = None) -> ProcessingPlan:
    restriction, parameters = _id_filter(external_ids)
    revision = os.environ.get("LYRICS_REVISION", "5617a9f61b028005a4858fdac845db406aefb181")
    with connection.cursor() as cursor:
        cursor.execute(
            f"""SELECT DISTINCT ts.external_id
                FROM track_sources ts LEFT JOIN lyrics l ON l.track_id=ts.track_id
                WHERE ts.source_type='subsonic'{restriction}
                  AND (l.track_id IS NULL OR l.text IS NULL OR NOT EXISTS (
                    SELECT 1 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                    WHERE e.track_id=ts.track_id AND e.embedding_type='lyrics'
                      AND e.window_index IS NULL AND ar.model_name='bge_m3'
                      AND ar.model_revision=%s
                  )) ORDER BY ts.external_id""",
            [*parameters, revision],
        )
        ids = tuple(str(row[0]) for row in cursor.fetchall())
    return ProcessingPlan(lyrics_external_ids=ids)


def plan_karaoke(connection: psycopg.Connection, pipeline_revision: str,
                  external_ids: Iterable[str] | None = None,
                  model_revision: str | None = None) -> ProcessingPlan:
    restriction, parameters = _id_filter(external_ids)
    with connection.cursor() as cursor:
        cursor.execute("SELECT karaoke_processing_enabled FROM analysis_settings WHERE singleton=true")
        setting = cursor.fetchone()
        if setting is not None and not bool(setting[0]):
            return ProcessingPlan()
        cursor.execute(
            f"""SELECT DISTINCT ts.external_id
                FROM track_sources ts JOIN lyrics l ON l.track_id=ts.track_id
                WHERE ts.source_type='subsonic'{restriction}
                  AND coalesce((l.provenance->>'synced')::boolean, false)
                  AND l.text IS NOT NULL
                  AND jsonb_typeof(l.provenance->'lines')='array'
                  AND jsonb_array_length(l.provenance->'lines') > 0
                  AND EXISTS (SELECT 1 FROM jsonb_array_elements(l.provenance->'lines') line
                              WHERE jsonb_typeof(line->'start_ms')='number')
                  AND NOT EXISTS (
                    SELECT 1 FROM karaoke_lyrics_variants kv
                    WHERE kv.track_id=l.track_id AND kv.bounded=false
                      AND kv.provenance->>'pipeline_revision'=%s
                      AND (%s::text IS NULL OR kv.model_revision=%s::text)
                  ) ORDER BY ts.external_id""",
            [*parameters, pipeline_revision, model_revision, model_revision],
        )
        ids = tuple(str(row[0]) for row in cursor.fetchall())
    return ProcessingPlan(karaoke_external_ids=ids)


def plan_audio(connection: psycopg.Connection, library_id, external_ids: Iterable[str]) -> AudioProcessingPlan:
    ids = list(external_ids)
    muq_revision = os.environ.get("MUQ_REVISION", "2e01c796b71dca71b45251384c04cd7b237c9020")
    mert_revision = os.environ.get("MERT_REVISION", "12af15fef9d0ac838c3f475bfbbf26d2060dd4f5")
    with connection.cursor() as cursor:
        cursor.execute(
            """SELECT requested.external_id,
                      ts.track_id,
                      EXISTS (SELECT 1 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                              WHERE e.track_id=ts.track_id AND e.embedding_type='audio-track'
                                AND e.window_index IS NULL AND ar.model_name='muq_mulan'
                                AND ar.model_revision=%s) AS has_muq,
                      EXISTS (SELECT 1 FROM embeddings e JOIN analysis_runs ar ON ar.id=e.run_id
                              WHERE e.track_id=ts.track_id AND e.embedding_type='audio-track'
                                AND e.window_index IS NULL AND ar.model_name='mert'
                                AND ar.model_revision=%s) AS has_mert,
                      EXISTS (SELECT 1 FROM track_fingerprints tf WHERE tf.track_id=ts.track_id) AS has_fingerprint,
                      EXISTS (SELECT 1 FROM melody_contours mc JOIN analysis_runs ar ON ar.id=mc.run_id
                              WHERE mc.track_id=ts.track_id AND ar.model_name='melody_contour'
                                AND ar.model_revision='multi-source-v1') AS has_melody
               FROM unnest(%s::text[]) requested(external_id)
               LEFT JOIN track_sources ts ON ts.library_id=%s AND ts.source_type='subsonic'
                                         AND ts.external_id=requested.external_id""",
            (muq_revision, mert_revision, ids, library_id),
        )
        rows = cursor.fetchall()
    return AudioProcessingPlan(
        frozenset(str(row[0]) for row in rows if not row[2]),
        frozenset(str(row[0]) for row in rows if not row[3]),
        frozenset(str(row[0]) for row in rows if not row[4]),
        frozenset(str(row[0]) for row in rows if not row[5]),
    )
