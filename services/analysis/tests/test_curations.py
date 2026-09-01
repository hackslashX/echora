import numpy as np
import pytest

import echora_analysis.concepts as concepts
from echora_analysis.curations import mode_transport_similarity, rank_curation


@pytest.fixture()
def fake_text_embeddings(monkeypatch):
    """Replace the MuQ text encoder with a deterministic lookup table."""
    table = {
        "guitars and piano": [1.0, 0.0],
        "distorted guitars": [1.0, 0.0],
        "guitars": [1.0, 0.0],
        "distortion": [0.9, 0.1],
        "warm acoustic": [0.7, 0.7],
        "pop": [1.0, 0.0],
        "japanese": [0.0, 1.0],
    }

    def embed(texts):
        return np.asarray([table[text] for text in texts], dtype=np.float32)

    monkeypatch.setattr(concepts, "embed_texts", embed)
    return table


def test_structured_sound_prompt_never_touches_the_lyrics_channel(fake_text_embeddings):
    rows = [
        {"id": "guitar-no-lyrics", "title": "Riff", "artist": "A", "recording_group_id": None},
        {"id": "on-theme-lyrics", "title": "Ballad", "artist": "B", "recording_group_id": None},
    ]
    # The guitar instrumental is semantically closer to the sound prompt, while
    # the vocal track wins on lyrics. Sound-only ranking must pick the guitar.
    matrix = np.asarray([[0.9, 0.1], [0.2, 0.8]], dtype=np.float32)
    lyrics_matrix = np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    lyrics_available = np.asarray([False, True])
    themes_query = np.asarray([[1.0, 0.0]], dtype=np.float32)

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=2, refresh_mode="fresh",
        lyrics_matrix=lyrics_matrix, lyrics_available=lyrics_available,
        shuffle_seed=1,
        sound_prompts=[["guitars and piano"]], themes_prompts=[],
        sound_weight=50,
    )
    top = max(selected, key=lambda row: row["score"])
    assert top["id"] == "guitar-no-lyrics"

    # A structured recipe with only themes has no semantic evidence to lose to,
    # so the thematic vocal track still ranks even without the sound channel.
    selected, evidence = rank_curation(
        rows, matrix, "", "", track_limit=2, refresh_mode="fresh",
        lyrics_matrix=lyrics_matrix, lyrics_available=lyrics_available,
        lyrics_positive_queries=themes_query,
        shuffle_seed=1,
        sound_prompts=[], themes_prompts=["heartbreak and love"],
        sound_weight=50,
    )
    top = max(selected, key=lambda row: row["score"])
    assert top["id"] == "on-theme-lyrics"


def test_structured_weight_shifts_the_blend(fake_text_embeddings):
    rows = [
        {"id": "sound-track", "title": "Riff", "artist": "A", "recording_group_id": None},
        {"id": "theme-track", "title": "Ballad", "artist": "B", "recording_group_id": None},
    ]
    matrix = np.asarray([[0.9, 0.1], [0.2, 0.8]], dtype=np.float32)
    lyrics_matrix = np.asarray([[0.0, 1.0], [1.0, 0.0]], dtype=np.float32)
    lyrics_available = np.asarray([True, True])
    themes_query = np.asarray([[1.0, 0.0]], dtype=np.float32)

    def winner(weight: int) -> str:
        selected, _ = rank_curation(
            rows, matrix, "", "", track_limit=1, refresh_mode="fresh",
            lyrics_matrix=lyrics_matrix, lyrics_available=lyrics_available,
            lyrics_positive_queries=themes_query,
            shuffle_seed=1,
            sound_prompts=[["distorted guitars"]], themes_prompts=[["heartbreak"]],
            sound_weight=weight,
        )
        return max(selected, key=lambda row: row["score"])["id"]

    assert winner(100) == "sound-track"
    assert winner(0) == "theme-track"


def test_negative_tags_only_affect_their_own_channel(fake_text_embeddings):
    rows = [
        {"id": "clean-guitar", "title": "Riff", "artist": "A", "recording_group_id": None},
        {"id": "distorted-guitar", "title": "Wall", "artist": "B", "recording_group_id": None},
    ]
    # Both tracks look identical to the positive sound tag; only the negative
    # sound tag separates them. Themes tags are absent, so the lyrics channel
    # stays inactive and cannot interfere.
    matrix = np.asarray([[1.0, 0.0], [0.95, 0.05]], dtype=np.float32)
    lyrics_matrix = np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32)
    lyrics_available = np.asarray([False, False])

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=1, refresh_mode="fresh",
        lyrics_matrix=lyrics_matrix, lyrics_available=lyrics_available,
        shuffle_seed=1,
        sound_prompts=[["guitars"]], sound_negative_prompts=[["distortion"]],
        sound_weight=50,
    )
    top = max(selected, key=lambda row: row["score"])
    assert top["id"] == "clean-guitar"
    assert all(row["evidence"]["lyrics_percentile"] == 0.5 for row in selected)


def test_negative_sound_tag_is_an_independent_soft_exclusion(fake_text_embeddings):
    rows = [
        {"id": "japanese", "title": "Japanese", "artist": "A", "recording_group_id": None},
        {"id": "english", "title": "English", "artist": "B", "recording_group_id": None},
        {"id": "other", "title": "Other", "artist": "C", "recording_group_id": None},
    ]
    matrix = np.asarray([[0.9, 0.8], [0.8, 0.05], [0.1, 0.2]], dtype=np.float32)

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=3, refresh_mode="fresh", shuffle_seed=1,
        sound_prompts=[["pop"]], sound_negative_prompts=[["japanese"]], sound_weight=100,
    )

    top = max(selected, key=lambda row: row["score"])
    assert top["id"] == "english"


def test_negative_theme_query_uses_embedded_vectors_as_soft_exclusions(fake_text_embeddings):
    rows = [
        {"id": "japanese", "title": "Japanese", "artist": "A", "recording_group_id": None},
        {"id": "english", "title": "English", "artist": "B", "recording_group_id": None},
        {"id": "other", "title": "Other", "artist": "C", "recording_group_id": None},
    ]
    matrix = np.eye(3, dtype=np.float32)
    lyrics = np.asarray([[0.8, 0.9], [0.9, 0.05], [0.1, 0.2]], dtype=np.float32)

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=3, refresh_mode="fresh", shuffle_seed=1,
        lyrics_matrix=lyrics, lyrics_available=np.ones(3, dtype=bool),
        lyrics_positive_queries=np.asarray([[1.0, 0.0]], dtype=np.float32),
        lyrics_negative_queries=np.asarray([[0.0, 1.0]], dtype=np.float32),
        sound_prompts=[], themes_prompts=[["pop"]], themes_negative_prompts=[["japanese"]],
        sound_weight=0,
    )

    top = max(selected, key=lambda row: row["score"])
    assert top["id"] == "english"


def test_legacy_prompt_keeps_the_historical_blend(fake_text_embeddings):
    rows = [
        {"id": "a", "title": "A", "artist": "A", "recording_group_id": None},
        {"id": "b", "title": "B", "artist": "B", "recording_group_id": None},
    ]
    matrix = np.eye(2, dtype=np.float32)
    legacy, _ = rank_curation(
        rows, matrix, "warm acoustic", "", track_limit=2, refresh_mode="fresh", shuffle_seed=1,
    )
    structured, _ = rank_curation(
        rows, matrix, "", "", track_limit=2, refresh_mode="fresh", shuffle_seed=1,
        sound_prompts=[["warm acoustic"]], themes_prompts=[["warm acoustic"]], sound_weight=45,
    )
    assert [row["id"] for row in legacy] == [row["id"] for row in structured]
    assert [row["score"] for row in legacy] == [row["score"] for row in structured]


def test_curation_selects_only_one_track_per_recording_group():
    rows = [
        {"id": "reference", "title": "Reference", "artist": "Artist A", "recording_group_id": None},
        {"id": "duplicate-high", "title": "Duplicate", "artist": "Artist B", "recording_group_id": "same-recording"},
        {"id": "duplicate-low", "title": "Duplicate reissue", "artist": "Artist C", "recording_group_id": "same-recording"},
        {"id": "other", "title": "Other", "artist": "Artist D", "recording_group_id": None},
    ]
    matrix = np.asarray([
        [1.0, 0.0],
        [0.99, 0.01],
        [0.98, 0.02],
        [0.8, 0.2],
    ], dtype=np.float32)

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=4, refresh_mode="fresh",
        positive_track_ids=["reference"], shuffle_seed=1,
    )

    selected_groups = [row.get("recording_group_id") for row in selected]
    assert selected_groups.count("same-recording") == 1
    assert len(selected) == 3


def test_mode_transport_conserves_duration_weights():
    left = (
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        np.asarray([0.9, 0.1], dtype=np.float32),
    )
    mostly_matching = (
        np.asarray([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
        np.asarray([0.8, 0.2], dtype=np.float32),
    )
    brief_matching = (
        np.asarray([[1.0, 0.0], [-1.0, 0.0]], dtype=np.float32),
        np.asarray([0.1, 0.9], dtype=np.float32),
    )

    assert mode_transport_similarity(left, mostly_matching) > mode_transport_similarity(
        left, brief_matching,
    )


def test_song_examples_use_mert_when_both_tracks_have_it():
    rows = [
        {"id": "reference", "title": "Reference", "artist": "A", "recording_group_id": None},
        {"id": "acoustic-match", "title": "Match", "artist": "B", "recording_group_id": None},
        {"id": "acoustic-miss", "title": "Miss", "artist": "C", "recording_group_id": None},
    ]
    # MuQ cannot distinguish the two candidates; MERT can.
    semantic = np.asarray([[1.0, 0.0], [0.8, 0.2], [0.8, 0.2]], dtype=np.float32)
    acoustic = np.asarray([[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]], dtype=np.float32)

    selected, _ = rank_curation(
        rows, semantic, "", "", track_limit=3, refresh_mode="fresh",
        positive_track_ids=["reference"], shuffle_seed=1,
        acoustic_matrix=acoustic, acoustic_available=np.ones(3, dtype=bool),
    )
    by_id = {row["id"]: row for row in selected}

    assert by_id["acoustic-match"]["score"] > by_id["acoustic-miss"]["score"]
    assert "positive_mert_global_similarity" in by_id["acoustic-match"]["evidence"]["example_similarity"]


def test_song_examples_fall_back_to_muq_when_the_reference_has_no_mert():
    rows = [
        {"id": "reference", "title": "Reference", "artist": "A", "recording_group_id": None},
        {"id": "semantic-match", "title": "Match", "artist": "B", "recording_group_id": None},
        {"id": "semantic-miss", "title": "Miss", "artist": "C", "recording_group_id": None},
    ]
    semantic = np.asarray([[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]], dtype=np.float32)
    acoustic = np.asarray([[0.0, 0.0], [0.0, 1.0], [1.0, 0.0]], dtype=np.float32)

    selected, _ = rank_curation(
        rows, semantic, "", "", track_limit=3, refresh_mode="fresh",
        positive_track_ids=["reference"], shuffle_seed=1,
        acoustic_matrix=acoustic,
        acoustic_available=np.asarray([False, True, True]),
    )
    by_id = {row["id"]: row for row in selected}

    assert by_id["semantic-match"]["score"] > by_id["semantic-miss"]["score"]
    assert "positive_mert_global_similarity" not in by_id["semantic-match"]["evidence"]["example_similarity"]


def test_no_musical_direction_is_explicitly_neutral():
    rows = [
        {"id": "a", "title": "A", "artist": "A", "recording_group_id": None},
        {"id": "b", "title": "B", "artist": "B", "recording_group_id": None},
    ]

    selected, _ = rank_curation(
        rows, np.eye(2, dtype=np.float32), "", "",
        track_limit=2, refresh_mode="fresh", shuffle_seed=1,
    )

    assert {track["score"] for track in selected} == {0.5}
    assert {track["percentile"] for track in selected} == {0.5}


def test_free_form_sound_direction_uses_duration_weighted_muq_modes(fake_text_embeddings):
    rows = [
        {"id": "mode-match", "title": "Match", "artist": "A", "recording_group_id": None},
        {"id": "mode-miss", "title": "Miss", "artist": "B", "recording_group_id": None},
    ]
    # Global vectors tie; their duration-weighted local identities separate them.
    global_vectors = np.asarray([[1.0, 1.0], [1.0, 1.0]], dtype=np.float32)
    modes = [
        (np.asarray([[1.0, 0.0]], dtype=np.float32), np.asarray([1.0], dtype=np.float32)),
        (np.asarray([[0.0, 1.0]], dtype=np.float32), np.asarray([1.0], dtype=np.float32)),
    ]

    selected, _ = rank_curation(
        rows, global_vectors, "pop", "", track_limit=2,
        refresh_mode="fresh", shuffle_seed=1, semantic_modes=modes,
    )
    by_id = {track["id"]: track for track in selected}

    assert by_id["mode-match"]["score"] > by_id["mode-miss"]["score"]


def test_manual_and_time_examples_are_independent_active_signals():
    rows = [
        {"id": "manual", "title": "Manual", "artist": "A", "recording_group_id": None},
        {"id": "time", "title": "Time", "artist": "B", "recording_group_id": None},
        {"id": "balanced", "title": "Balanced", "artist": "C", "recording_group_id": None},
        {"id": "manual-only", "title": "Manual only", "artist": "D", "recording_group_id": None},
        {"id": "time-only", "title": "Time only", "artist": "E", "recording_group_id": None},
    ]
    matrix = np.asarray([
        [1.0, 0.0], [0.0, 1.0], [0.7, 0.7], [0.99, 0.1], [0.1, 0.99],
    ], dtype=np.float32)

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=5, refresh_mode="fresh",
        positive_track_ids=["manual"], context_track_ids=["time"], shuffle_seed=1,
    )
    by_id = {track["id"]: track for track in selected}

    assert by_id["balanced"]["score"] > by_id["manual-only"]["score"]
    assert by_id["balanced"]["score"] > by_id["time-only"]["score"]
    assert "time_positive_muq_global_similarity" in by_id["balanced"]["evidence"]["example_similarity"]


def test_ineligible_reference_can_guide_an_eligible_language_pool():
    rows = [
        {"id": "outside-reference", "title": "Reference", "artist": "A", "recording_group_id": None},
        {"id": "eligible-match", "title": "Match", "artist": "B", "recording_group_id": None},
        {"id": "eligible-miss", "title": "Miss", "artist": "C", "recording_group_id": None},
    ]
    matrix = np.asarray([[1.0, 0.0], [0.95, 0.05], [0.0, 1.0]], dtype=np.float32)

    selected, _ = rank_curation(
        rows, matrix, "", "", track_limit=2, refresh_mode="fresh",
        positive_track_ids=["outside-reference"],
        eligible_track_ids={"eligible-match", "eligible-miss"}, shuffle_seed=1,
    )

    assert {track["id"] for track in selected} == {"eligible-match", "eligible-miss"}
    by_id = {track["id"]: track for track in selected}
    assert by_id["eligible-match"]["score"] > by_id["eligible-miss"]["score"]
