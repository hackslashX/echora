import pytest
from echora_analysis.song_transcription import parse_window, windows
from echora_analysis.transcription_config import transcription_model


def test_windows_cover_full_song_with_overlap():
    ranges = list(windows(221.55))
    assert ranges == [(0,60),(48,108),(96,156),(144,204),(192,221.55)]
    assert list(windows(12)) == [(0,12)]


def test_keep_multi_and_original_overlap():
    lines = parse_window('[1.00][S01]hello[3.00][2.00][MULTI]world[4.00]', 48, 60)
    assert lines[0]['start_ms'] == 49000
    assert lines[1]['speaker'] == 'MULTI'
    assert lines[1]['start_ms'] < lines[0]['end_ms']


@pytest.mark.parametrize('text', ['[1.00][S01]unfinished', '[2.00][S01]bad[1.00]', '[0.00][S01]bad[61.00]', '[0.00][UNKNOWN]bad[1.00]', ''])
def test_invalid_generation_is_not_published(text):
    with pytest.raises(ValueError): parse_window(text, 0, 60)


def test_model_config_requires_pinned_revision(monkeypatch):
    monkeypatch.delenv('MOSS_MODEL_ID', raising=False)
    monkeypatch.delenv('MOSS_REVISION', raising=False)
    assert transcription_model() is None
    monkeypatch.setenv('MOSS_MODEL_ID','example/model')
    with pytest.raises(ValueError): transcription_model()
    monkeypatch.setenv('MOSS_REVISION','a'*40)
    assert transcription_model() == ('example/model','a'*40)
