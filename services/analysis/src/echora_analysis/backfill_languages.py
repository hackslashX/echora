"""One-off backfill: compute language distributions for already-stored lyrics.

Run inside the analysis container:

    python -m echora_analysis.backfill_languages

Updates `lyrics.language` with the detected primary language (replacing the
useless Navidrome 'xxx') and stores the distribution under
`provenance.languages`.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .language_detection import detect_distribution

BATCH_SIZE = 200


def _batches(connection: psycopg.Connection) -> Iterator[list[dict[str, object]]]:
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            """SELECT track_id, text, provenance FROM lyrics
               WHERE text IS NOT NULL AND length(text) > 0
               ORDER BY track_id""")
        while True:
            rows = cursor.fetchmany(BATCH_SIZE)
            if not rows:
                return
            yield rows


def backfill() -> None:
    database_url = os.environ["DATABASE_URL"]
    updated = 0
    unconfident = 0
    with psycopg.connect(database_url) as connection:
        for batch in _batches(connection):
            payload = []
            for row in batch:
                provenance = row["provenance"] if isinstance(row["provenance"], dict) else {}
                distribution = detect_distribution(str(row["text"]))
                next_provenance = {**provenance, "languages": distribution} if distribution else {
                    key: value for key, value in provenance.items() if key != "languages"
                }
                if distribution and not distribution["confident"]:
                    unconfident += 1
                primary = distribution.get("primary_language") if distribution else None
                payload.append((primary, Jsonb(next_provenance), row["track_id"]))
            with connection.cursor() as cursor:
                cursor.executemany(
                    """UPDATE lyrics SET language=%s, provenance=%s WHERE track_id=%s""",
                    payload,
                )
            updated += len(payload)
            print(f"processed {updated} tracks", flush=True)
    print(f"done: {updated} tracks updated, {unconfident} flagged low-confidence")


if __name__ == "__main__":
    backfill()
