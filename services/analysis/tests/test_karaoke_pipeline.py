from echora_analysis.karaoke_pipeline import parse_ass_karaoke


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
