from datetime import datetime, timezone

from echora_analysis.listening_history import Listen, track_listen_counts


def test_track_listen_counts_matches_tracks_and_overnight_periods():
    rows = [{"id": "one", "title": "A Song", "artist": "An Artist"}]
    listens = [
        Listen("An Artist", "A Song", datetime(2026, 8, 24, 23, 30, tzinfo=timezone.utc)),
        Listen("An Artist", "A Song", datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)),
    ]

    all_counts, period_counts = track_listen_counts(rows, listens, "UTC", "22:00", "02:00")

    assert all_counts == {"one": 2}
    assert period_counts == {"one": 1}
