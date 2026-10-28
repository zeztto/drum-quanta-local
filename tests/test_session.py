import hashlib
import io
import zipfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from src.core.session import Session


def archive_audio(tmp_path, tracks, sr=8000):
    archive = tmp_path / "tracks.zip"
    with zipfile.ZipFile(archive, "w") as output:
        for name, audio in tracks.items():
            data = io.BytesIO()
            sf.write(data, audio, sr, format="WAV", subtype="FLOAT")
            output.writestr(name, data.getvalue())
    return archive


def signal():
    sr = 8000
    audio = 0.01 * np.sin(2 * np.pi * 60 * np.arange(sr * 3) / sr)
    for location in (1900, 6100, 10300, 14500, 18700):
        audio[location : location + 200] += 0.65 * np.exp(-np.arange(200) / 30)
    return audio.astype("float32")


def test_actual_reference_detection_common_plan_and_wav_zip_decode(tmp_path):
    a = signal()
    archive = archive_audio(
        tmp_path, {"kick.wav": a, "snare.wav": a * 0.5, "room.wav": a * 0.25}
    )
    original_hash = hashlib.sha256(archive.read_bytes()).hexdigest()
    session = Session()
    try:
        session.analyze(archive)
        report = session.quantize(
            "kick.wav", ["kick.wav", "snare.wav"], 120, "1/16", 80
        )
        assert report["hits"] > 0
        assert len(session.onsets) == len(session.targets)
        np.testing.assert_allclose(
            session.processed[2], session.processed[0] * 0.5, atol=1e-8
        )
        np.testing.assert_array_equal(session.processed[1], session.audio[1])
        outputs = session.export()
        with zipfile.ZipFile(outputs[-1]) as zipped:
            assert len(zipped.namelist()) == 3
            decoded = [
                sf.read(io.BytesIO(zipped.read(name)))[0] for name in zipped.namelist()
            ]
            for index, output in enumerate(decoded):
                np.testing.assert_allclose(output, session.processed[index], atol=4e-8)
        assert hashlib.sha256(archive.read_bytes()).hexdigest() == original_hash
    finally:
        session.close()


def test_zero_hit_and_strength_zero_preserve_samples(tmp_path):
    session = Session()
    try:
        session.analyze(archive_audio(tmp_path, {"silence.wav": np.zeros(8000)}))
        result = session.quantize("silence.wav", ["silence.wav"], 120, "1/16", 100)
        assert result["hits"] == 0 and result["max_shift_samples"] == 0
        np.testing.assert_array_equal(session.processed[0], session.audio[0])
        session.analyze(archive_audio(tmp_path, {"kick.wav": signal()}))
        session.quantize("kick.wav", ["kick.wav"], 120, "1/16", 0)
        np.testing.assert_array_equal(session.processed[0], session.audio[0])
    finally:
        session.close()


def test_sessions_and_cleanup_are_isolated(tmp_path):
    first, second = Session(), Session()
    archive = archive_audio(tmp_path, {"kick.wav": signal()})
    first.analyze(archive)
    second.analyze(archive)
    first.close()
    try:
        assert second.root.exists() and Path(second.files[0]).is_file()
        second.quantize("kick.wav", ["kick.wav"], 120, "1/16", 0)
        assert all(Path(p).is_file() for p in second.export())
    finally:
        second.close()


@pytest.mark.parametrize(
    "audio,sr",
    [(np.zeros((100, 2)), 8000), (np.zeros(100), 4000), (np.zeros(121 * 8000), 8000)],
)
def test_audio_channel_rate_duration_limits(tmp_path, audio, sr):
    session = Session()
    try:
        with pytest.raises(ValueError):
            session.analyze(archive_audio(tmp_path, {"bad.wav": audio}, sr))
    finally:
        session.close()


def test_total_sample_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(Session, "MAX_TOTAL_SAMPLES", 100)
    session = Session()
    try:
        with pytest.raises(ValueError):
            session.analyze(archive_audio(tmp_path, {"bad.wav": np.zeros(101)}))
    finally:
        session.close()


def test_mismatched_lengths_are_rejected(tmp_path):
    session = Session()
    try:
        with pytest.raises(ValueError):
            session.analyze(
                archive_audio(
                    tmp_path, {"one.wav": np.zeros(1000), "two.wav": np.zeros(2000)}
                )
            )
    finally:
        session.close()


def test_targz_regular_audio_uses_same_group_plan(tmp_path):
    import tarfile

    a = signal()
    archive = tmp_path / "tracks.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, audio in [("kick.wav", a), ("snare.wav", a * 0.5)]:
            stream = io.BytesIO()
            sf.write(stream, audio, 8000, format="WAV", subtype="FLOAT")
            payload = stream.getvalue()
            info = tarfile.TarInfo("tracks/" + name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    session = Session()
    try:
        session.analyze(archive)
        assert (
            session.quantize("kick.wav", ["kick.wav", "snare.wav"], 120, "1/16", 80)[
                "hits"
            ]
            == 4
        )
        np.testing.assert_allclose(
            session.processed[1], session.processed[0] * 0.5, atol=1e-8
        )
    finally:
        session.close()
