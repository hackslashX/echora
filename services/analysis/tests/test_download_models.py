from echora_analysis.download_models import _pin_main_ref


def test_pin_main_ref_points_to_snapshot_commit(tmp_path) -> None:
    snapshot = tmp_path / "models--example" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)

    _pin_main_ref(str(snapshot))

    assert (tmp_path / "models--example" / "refs" / "main").read_text() == "abc123"
