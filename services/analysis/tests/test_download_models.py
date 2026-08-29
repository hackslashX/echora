from unittest.mock import Mock

import pytest

from echora_analysis.download_models import _download_demucs, _pin_main_ref


def test_pin_main_ref_points_to_snapshot_commit(tmp_path) -> None:
    snapshot = tmp_path / "models--example" / "snapshots" / "abc123"
    snapshot.mkdir(parents=True)

    _pin_main_ref(str(snapshot))

    assert (tmp_path / "models--example" / "refs" / "main").read_text() == "abc123"


def test_download_demucs_defaults_to_fine_tuned_model(monkeypatch, tmp_path) -> None:
    get_model = Mock()
    monkeypatch.setenv("FA_KARA_VOCAL_SEPARATION", "true")
    monkeypatch.delenv("FA_KARA_DEMUCS_MODEL", raising=False)
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    monkeypatch.setattr("echora_analysis.download_models.pretrained.get_model", get_model)

    _download_demucs()

    get_model.assert_called_once_with("htdemucs_ft")


def test_download_demucs_removes_unused_standard_checkpoint(monkeypatch, tmp_path) -> None:
    checkpoint = tmp_path / "hub" / "checkpoints" / "955717e8-8726e21a.th"
    checkpoint.parent.mkdir(parents=True)
    checkpoint.write_bytes(b"obsolete")
    monkeypatch.setenv("FA_KARA_VOCAL_SEPARATION", "false")
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))
    monkeypatch.setattr("echora_analysis.download_models.pretrained.get_model", Mock())

    _download_demucs()

    assert not checkpoint.exists()


def test_download_demucs_rejects_unknown_model(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("FA_KARA_VOCAL_SEPARATION", "true")
    monkeypatch.setenv("FA_KARA_DEMUCS_MODEL", "unknown")
    monkeypatch.setenv("TORCH_HOME", str(tmp_path))

    with pytest.raises(ValueError, match="FA_KARA_DEMUCS_MODEL"):
        _download_demucs()
