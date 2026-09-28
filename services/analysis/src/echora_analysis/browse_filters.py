"""Allowlisted SQL predicates shared by browse count and page queries."""
from fastapi import HTTPException


def predicates(*, vocals='', language='', lyrics='', translation='', genre='', year_from=None, year_to=None):
    clauses, params = [], []
    def add(sql, *values):
        clauses.append(sql)
        params.extend(values)
    if year_from is not None and year_to is not None and year_from > year_to:
        raise HTTPException(422, 'Release year range is reversed')
    if genre:
        add('t.genres @> ARRAY[%s]::text[]', genre)
    if year_from is not None:
        add('t.year >= %s', year_from)
    if year_to is not None:
        add('t.year <= %s', year_to)
    if language:
        languages = list(dict.fromkeys(language.split(',')))
        if len(languages) > 32:
            raise HTTPException(422, 'Too many languages')
        known = [item for item in languages if item != 'unknown']
        pieces = []
        if known:
            pieces.append('EXISTS (SELECT 1 FROM lyrics bl WHERE bl.track_id=t.id AND bl.language=ANY(%s))')
            params.append(known)
        if 'unknown' in languages:
            pieces.append("NOT EXISTS (SELECT 1 FROM lyrics bl WHERE bl.track_id=t.id AND NULLIF(bl.language,'') IS NOT NULL)")
        clauses.append('(' + ' OR '.join(pieces) + ')')
    if lyrics:
        if lyrics == 'available':
            add("EXISTS (SELECT 1 FROM lyrics bl WHERE bl.track_id=t.id AND NULLIF(btrim(bl.text),'') IS NOT NULL)")
        elif lyrics == 'missing':
            add("NOT EXISTS (SELECT 1 FROM lyrics bl WHERE bl.track_id=t.id AND NULLIF(btrim(bl.text),'') IS NOT NULL)")
        elif lyrics == 'ai':
            add("EXISTS (SELECT 1 FROM lyrics bl WHERE bl.track_id=t.id AND bl.provenance->>'ai_generated'='true')")
        else:
            raise HTTPException(422, 'Unknown lyrics filter')
    if translation:
        add("EXISTS (SELECT 1 FROM lyric_translations bt WHERE bt.track_id=t.id AND bt.status='ready' AND bt.target_language=%s)", translation)
    if vocals:
        if vocals not in {'instrumental', 'vocal', 'female', 'male', 'unknown'}:
            raise HTTPException(422, 'Unknown vocals filter')
        base = "SELECT 1 FROM current_embeddings be WHERE be.track_id=t.id AND be.embedding_type='voice-gender' AND be.window_index IS NULL"
        if vocals == 'unknown':
            add('NOT EXISTS (' + base + ')')
        else:
            # Same instrumental threshold as curation; gender is dominant model evidence, not identity.
            score = '(be.embedding::real[])'
            condition = {'instrumental': f'{score}[1] >= 0.5', 'vocal': f'{score}[1] < 0.5',
                         'female': f'{score}[1] < 0.5 AND {score}[2] >= {score}[3]',
                         'male': f'{score}[1] < 0.5 AND {score}[3] > {score}[2]'}[vocals]
            add('EXISTS (' + base + ' AND ' + condition + ')')
    return clauses, params
