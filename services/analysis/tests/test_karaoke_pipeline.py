from echora_analysis.karaoke_pipeline import (
    _anchored_source_lines,
    _stored_model_revision,
    apply_adaptive_line_padding,
    build_lines_from_alignment_document,
    _timed_source_lines,
    _validate_alignment_document,
    bound_to_synced_lines,
    guard_pathological_lead_ins,
    parse_ass_karaoke,
    stabilize_to_synced_lines,
)


def test_stored_model_revision_tracks_vocal_separator(monkeypatch):
    monkeypatch.setenv("FA_KARA_VOCAL_SEPARATION", "true")
    monkeypatch.setenv("FA_KARA_DEMUCS_MODEL", "htdemucs_ft")

    assert _stored_model_revision("model-revision").endswith(
        ":model-revision:demucs:htdemucs_ft"
    )


def test_stored_model_revision_omits_separator_for_full_mix(monkeypatch):
    monkeypatch.setenv("FA_KARA_VOCAL_SEPARATION", "false")

    assert _stored_model_revision("model-revision").endswith(":model-revision")
    assert ":demucs:" not in _stored_model_revision("model-revision")


def test_parse_ass_karaoke_preserves_line_and_syllable_timing():
    ass = (
        "[Events]\n"
        "Dialogue: 0,0:00:01.00,0:00:03.20,Default,,0,0,0,karaoke,{\\k20}{\\k50}Hel{\\k70}lo{\\k80}\n"
    )

    assert parse_ass_karaoke(ass) == [{
        "start_ms": 1000,
        "end_ms": 3200,
        "text": "Hello",
        "syllables": [
            {"start_ms": 1200, "end_ms": 1700, "text": "Hel"},
            {"start_ms": 1700, "end_ms": 2400, "text": "lo"},
        ],
    }]


def test_alignment_document_restores_punctuation_and_spaces_to_display_syllables():
    document = {"alignment": {"lines": [{
        "text": "Hello, world!",
        "start_ms": 1000,
        "end_ms": 1800,
        "tokens": [
            {"text": "Hello", "start_ms": 1000, "end_ms": 1300},
            {"text": "world", "start_ms": 1400, "end_ms": 1800},
        ],
    }]}}

    assert build_lines_from_alignment_document(document) == [{
        "text": "Hello, world!",
        "start_ms": 1000,
        "end_ms": 1800,
        "syllables": [
            {"text": "Hello, ", "start_ms": 1000, "end_ms": 1300},
            {"text": "world!", "start_ms": 1400, "end_ms": 1800},
        ],
    }]


def test_adaptive_padding_never_steals_time_from_previous_syllable():
    lines = [
        {"text": "uh-huh", "start_ms": 800, "end_ms": 2200,
         "syllables": [{"text": "uh-huh", "start_ms": 1000, "end_ms": 2000}]},
        {"text": "next", "start_ms": 1800, "end_ms": 3000,
         "syllables": [{"text": "next", "start_ms": 2000, "end_ms": 2400}]},
    ]

    result = apply_adaptive_line_padding(lines)

    assert result[0]["end_ms"] == 2000
    assert result[1]["start_ms"] == 2000
    assert result[0]["syllables"] == lines[0]["syllables"]


def test_adaptive_padding_uses_real_silence_and_syllable_duration():
    lines = [
        {"text": "first", "syllables": [{"text": "first", "start_ms": 1000, "end_ms": 1400}]},
        {"text": "second", "syllables": [{"text": "second", "start_ms": 2000, "end_ms": 2400}]},
    ]

    result = apply_adaptive_line_padding(lines)

    assert result[0]["end_ms"] == 1500
    assert result[1]["start_ms"] == 1900


def test_lead_in_guard_matches_source_text_after_blank_lines():
    karaoke = [{"text": "'Cause everything", "start_ms": 72877, "end_ms": 77179, "syllables": [
        {"text": "'Cause ", "start_ms": 72877, "end_ms": 72977},
        {"text": "ev", "start_ms": 72977, "end_ms": 76719},
        {"text": "erything", "start_ms": 76719, "end_ms": 77179},
    ]}]
    source = [
        {"text": "", "start_ms": 62660},
        {"text": "Other line", "start_ms": 68950},
        {"text": "'Cause everything", "start_ms": 76020},
    ]

    result = guard_pathological_lead_ins(karaoke, source, {})

    assert result[0]["start_ms"] == 76020
    assert result[0]["syllables"][0]["start_ms"] == 76020
    assert result[0]["syllables"][1]["start_ms"] == 76120
    assert result[0]["syllables"][2]["start_ms"] == 76719


def test_parse_ass_karaoke_ignores_headers():
    assert parse_ass_karaoke("[Script Info]\nTitle: example\n") == []


def test_timed_source_lines_filters_untimed_and_empty_entries():
    assert _timed_source_lines([
        {"text": " First line ", "start_ms": 1000},
        {"text": "", "start_ms": 1500},
        {"text": "Untimed"},
        {"text": "Second line", "start_ms": 2200.9},
    ]) == [
        {"text": "First line", "start_ms": 1000},
        {"text": "Second line", "start_ms": 2200},
    ]


def test_anchored_source_lines_interpolates_without_dropping_lyrics():
    assert _anchored_source_lines([
        {"text": "One", "start_ms": 1000},
        {"text": "Missing"},
        {"text": "Three", "start_ms": 5000},
    ]) == [
        {"text": "One", "start_ms": 1000, "interpolated": False},
        {"text": "Missing", "start_ms": 3000, "interpolated": True},
        {"text": "Three", "start_ms": 5000, "interpolated": False},
    ]


def test_stabilize_to_synced_lines_shifts_the_whole_line_not_only_first_syllable():
    karaoke = [{"text": "Learn to sign", "start_ms": 5500, "end_ms": 7000, "syllables": [
        {"text": "Learn", "start_ms": 5700, "end_ms": 6000},
        {"text": " to", "start_ms": 6000, "end_ms": 6300},
        {"text": " sign", "start_ms": 6300, "end_ms": 6800},
    ]}]

    result = stabilize_to_synced_lines(karaoke, [{"text": "Learn to sign", "start_ms": 6500}])

    assert result[0]["start_ms"] == 6500
    assert result[0]["syllables"] == [
        {"text": "Learn", "start_ms": 6500, "end_ms": 6800},
        {"text": " to", "start_ms": 6800, "end_ms": 7100},
        {"text": " sign", "start_ms": 7100, "end_ms": 7600},
    ]


def test_validate_alignment_document_accepts_monotonic_structured_output():
    document = {
        "schema_version": 1,
        "alignment": {"lines": [{
            "source_index": 0,
            "tokens": [{"start_ms": 100, "end_ms": 200, "ctc_score": 0.8}],
        }]},
        "diagnostics": {"inference_passes": 1},
    }

    assert _validate_alignment_document(document) is document


def test_validate_alignment_document_rejects_reversed_tokens():
    document = {
        "schema_version": 1,
        "alignment": {"lines": [{
            "source_index": 0,
            "tokens": [
                {"start_ms": 200, "end_ms": 300, "ctc_score": 0.8},
                {"start_ms": 100, "end_ms": 150, "ctc_score": 0.9},
            ],
        }]},
    }

    try:
        _validate_alignment_document(document)
    except RuntimeError as error:
        assert "non-monotonic" in str(error)
    else:
        raise AssertionError("expected document validation failure")


def test_guard_pathological_lead_ins_delays_only_stretched_first_syllable():
    diagnostics = {"source_offset_ms": 0, "source_drift_ms_per_minute": 0}
    result = guard_pathological_lead_ins([{
        "text": "Siento frío", "start_ms": 197680, "end_ms": 205110,
        "syllables": [
            {"text": "Sien", "start_ms": 197880, "end_ms": 203830},
            {"text": "to", "start_ms": 203990, "end_ms": 204470},
        ],
    }], [{"text": "Siento frío", "start_ms": 204010}], diagnostics)

    assert result[0]["start_ms"] == 203810
    assert result[0]["syllables"] == [
        {"text": "Sien", "start_ms": 204010, "end_ms": 204110},
        {"text": "to", "start_ms": 204110, "end_ms": 204470},
    ]
    assert diagnostics["pathological_lead_in_guarded_lines"] == [0]


def test_bound_to_synced_lines_clamps_syllables_to_source_window():
    karaoke = [{"text": "First line", "start_ms": 800, "end_ms": 2400, "syllables": [
        {"text": "First", "start_ms": 900, "end_ms": 1300},
        {"text": " line", "start_ms": 1900, "end_ms": 2400},
    ]}]
    source = [{"text": "First line", "start_ms": 1000}, {"text": "Second line", "start_ms": 2000}]

    result = bound_to_synced_lines(karaoke, source)

    assert result[0]["start_ms"] == 1000
    assert result[0]["end_ms"] == 2000
    assert result[0]["syllables"] == [
        {"text": "First", "start_ms": 1000, "end_ms": 1300},
        {"text": " line", "start_ms": 1900, "end_ms": 2000},
    ]
