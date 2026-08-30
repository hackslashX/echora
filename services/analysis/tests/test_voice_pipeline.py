import numpy as np
import pytest

from echora_analysis.voice_pipeline import _aggregate_outputs


def test_voice_gender_keeps_vocal_presence_in_joint_scores() -> None:
    gender = np.array([[0.9, 0.1], [0.2, 0.8]], dtype=np.float32)
    voice = np.array([[0.1, 0.9], [0.8, 0.2]], dtype=np.float32)

    scores = _aggregate_outputs(gender, voice)

    assert sum(scores.values()) == pytest.approx(1.0)
    assert scores["instrumental"] == pytest.approx(0.45)
    assert scores["female"] == pytest.approx(0.425)
    assert scores["male"] == pytest.approx(0.125)


def test_instrumental_audio_does_not_get_decisive_gender_score() -> None:
    gender = np.array([[0.99, 0.01]], dtype=np.float32)
    voice = np.array([[0.98, 0.02]], dtype=np.float32)

    scores = _aggregate_outputs(gender, voice)

    assert scores["instrumental"] == pytest.approx(0.98)
    assert scores["female"] < 0.02
    assert scores["male"] < 0.001


def test_classifier_output_shapes_are_validated() -> None:
    with pytest.raises(ValueError, match="Unexpected classifier output shapes"):
        _aggregate_outputs(np.ones((2, 2)), np.ones((3, 2)))
