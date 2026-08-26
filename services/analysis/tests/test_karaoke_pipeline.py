from echora_analysis.karaoke_pipeline import (
    _timed_source_lines,
    bound_to_synced_lines,
    parse_ass_karaoke,
    stabilize_to_synced_lines,
)


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
