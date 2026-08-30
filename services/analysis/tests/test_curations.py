import numpy as np

from echora_analysis.curations import rank_curation


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
