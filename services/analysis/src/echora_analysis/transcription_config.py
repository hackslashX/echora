"""Optional published MOSS checkpoint. No implicit upstream-model fallback."""
import os
import re


def transcription_model() -> tuple[str, str] | None:
    model = os.getenv('MOSS_MODEL_ID', '').strip()
    revision = os.getenv('MOSS_REVISION', '').strip()
    if not model and not revision:
        return None
    if not model or not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Set both MOSS_MODEL_ID and an immutable 40-character MOSS_REVISION')
    return model, revision


def transcription_enabled(connection):
    with connection.cursor() as cursor:
        cursor.execute("SELECT transcription_processing_enabled FROM analysis_settings WHERE singleton=true")
        row = cursor.fetchone()
    return bool(row and row[0])
