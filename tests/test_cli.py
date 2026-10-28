import hashlib
import io
import json
import os
import stat
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from tests.test_session import archive_audio, signal

pytestmark = pytest.mark.skipif(
    os.name != "posix", reason="POSIX descriptor and permission contract"
)
ROOT = Path(__file__).resolve().parents[1]


def invoke(tmp_path, archive, output, strength=80, reference="kick.wav"):
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "drum_quanta",
            "--input",
            str(archive),
            "--reference",
            reference,
            "--apply",
            "kick.wav",
            "--apply",
            "snare.wav",
            "--bpm",
            "120",
            "--grid",
            "1/16",
            "--strength",
            str(strength),
            "--output",
            str(output),
        ],
        check=False,
        cwd=ROOT,
        env={**os.environ, "TMPDIR": str(scratch)},
        capture_output=True,
        text=True,
    )
    assert list(scratch.iterdir()) == [], (
        "CLI must remove only its scratch directories on exit"
    )
    return result


def test_actual_cli_shared_plan_decode_readonly_input_and_no_overwrite(tmp_path):
    a = signal()
    archive = archive_audio(
        tmp_path, {"kick.wav": a, "snare.wav": a * 0.5, "room.wav": a * 0.25}
    )
    archive.chmod(0o444)
    before = (
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        stat.S_IMODE(archive.stat().st_mode),
    )
    output = tmp_path / "new-output"
    result = invoke(tmp_path, archive, output)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["hits"] == 4 and len(report["enabled"]) == 2
    assert len(report["original_onsets"]) == len(report["target_onsets"]) == 4
    decoded = {}
    for item in report["files"]:
        path = output / item["path"]
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        if path.suffix == ".wav":
            decoded[path.name], sr = sf.read(path, dtype="float32")
            assert sr == 8000 and sf.info(path).subtype == "FLOAT"
    np.testing.assert_allclose(
        decoded["03_snare_quantized.wav"],
        decoded["01_kick_quantized.wav"] * 0.5,
        atol=4e-8,
    )
    np.testing.assert_array_equal(decoded["02_room_quantized.wav"], a * 0.25)
    with zipfile.ZipFile(output / "drum-quanta-tracks.zip") as zipped:
        assert len(zipped.namelist()) == 3
        for name in zipped.namelist():
            audio, sr = sf.read(io.BytesIO(zipped.read(name)), dtype="float32")
            np.testing.assert_array_equal(audio, decoded[name])
    assert before == (
        hashlib.sha256(archive.read_bytes()).hexdigest(),
        stat.S_IMODE(archive.stat().st_mode),
    )
    existing = {p.name: p.read_bytes() for p in output.iterdir()}
    again = invoke(tmp_path, archive, output)
    assert again.returncode == 2 and "이미 존재" in again.stderr
    assert existing == {p.name: p.read_bytes() for p in output.iterdir()}
    assert stat.S_IMODE(output.stat().st_mode) == 0o700


@pytest.mark.parametrize("silence,strength", [(False, 0), (True, 80)])
def test_actual_cli_zero_strength_or_no_hit_preserves_samples(
    tmp_path, silence, strength
):
    a = np.zeros(24000, dtype="float32") if silence else signal()
    archive = archive_audio(tmp_path, {"kick.wav": a, "snare.wav": a * 0.5})
    output = tmp_path / "output"
    result = invoke(tmp_path, archive, output, strength)
    assert result.returncode == 0, result.stderr
    if silence:
        assert json.loads(result.stdout)["hits"] == 0
    np.testing.assert_array_equal(
        sf.read(output / "01_kick_quantized.wav", dtype="float32")[0], a
    )


@pytest.mark.parametrize("kind", ["bad-archive", "wrong-reference", "bad-strength"])
def test_actual_cli_failure_cleans_owned_scratch_and_preserves_neighbor(tmp_path, kind):
    archive = archive_audio(
        tmp_path, {"kick.wav": signal(), "snare.wav": signal() * 0.5}
    )
    if kind == "bad-archive":
        archive.write_bytes(b"broken ZIP")
    sentinel = tmp_path / "sentinel"
    sentinel.write_bytes(b"keep")
    output = tmp_path / "output"
    result = invoke(
        tmp_path,
        archive,
        output,
        strength=101 if kind == "bad-strength" else 80,
        reference="missing.wav" if kind == "wrong-reference" else "kick.wav",
    )
    assert result.returncode == 2
    assert not output.exists()
    assert sentinel.read_bytes() == b"keep"


def test_cli_export_failure_removes_only_created_output(tmp_path, monkeypatch):
    from argparse import Namespace

    from drum_quanta import run
    from src.core.session import Session

    archive = archive_audio(tmp_path, {"kick.wav": signal()})
    output = tmp_path / "output"
    neighbor = tmp_path / "neighbor"
    neighbor.mkdir()
    (neighbor / "keep").write_bytes(b"keep")

    def fail_after_first(self):
        first = self.root / "first.wav"
        first.write_bytes(b"owned partial output")
        return [str(first), str(self.root / "missing.wav")]

    monkeypatch.setattr(Session, "export", fail_after_first)
    args = Namespace(
        input=str(archive),
        reference="kick.wav",
        apply=["kick.wav"],
        bpm=120,
        grid="1/16",
        strength=80,
        output=str(output),
    )
    with pytest.raises(OSError):
        run(args)
    assert not output.exists()
    assert (neighbor / "keep").read_bytes() == b"keep"
