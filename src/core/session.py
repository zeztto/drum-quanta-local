"""Per-invocation grouped processing. No input normalization or microphone alignment."""

import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .archive_handler import ArchiveHandler
from .quantizer import Quantizer
from .transient_detect import TransientDetector


class Session:
    MAX_DURATION = 120
    MAX_TOTAL_SAMPLES = 16_000_000
    MIN_SR = 8000
    MAX_SR = 192000

    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="drum-quanta-session-"))
        self.archive = ArchiveHandler()
        self.files = []
        self.audio = []
        self.sample_rate = None
        self.processed = None
        self.onsets = np.array([], dtype=int)
        self.targets = np.array([], dtype=int)

    def close(self):
        self.archive.cleanup_all()
        shutil.rmtree(self.root, ignore_errors=True)

    def analyze(self, archive_path):
        directory, files = self.archive.extract_archive(str(archive_path))
        loaded = []
        total = 0
        rate = frames = None
        try:
            for filename in files:
                info = sf.info(filename)
                if info.channels != 1:
                    raise ValueError("각 트랙은 mono 1채널이어야 합니다.")
                if not self.MIN_SR <= info.samplerate <= self.MAX_SR:
                    raise ValueError("샘플레이트는 8–192 kHz 범위여야 합니다.")
                if info.frames <= 0 or info.duration > self.MAX_DURATION:
                    raise ValueError("각 트랙은 0초 초과·120초 이하여야 합니다.")
                total += info.frames
                if total > self.MAX_TOTAL_SAMPLES:
                    raise ValueError("전체 샘플 수 제한을 초과했습니다.")
                if rate is not None and (
                    info.samplerate != rate or info.frames != frames
                ):
                    raise ValueError(
                        "모든 트랙은 같은 샘플레이트·길이·시작 위치여야 합니다."
                    )
                rate, frames = info.samplerate, info.frames
                audio, _ = sf.read(filename, dtype="float32", frames=info.frames + 1)
                if len(audio) != info.frames:
                    raise ValueError("오디오 길이 정보가 일치하지 않습니다.")
                if not np.isfinite(audio).all():
                    raise ValueError("오디오에 유효하지 않은 숫자가 있습니다.")
                loaded.append(audio)
        except Exception:
            self.archive.cleanup_temp_dir(directory)
            raise
        for previous in tuple(self.archive._temp_dirs):
            if previous != directory:
                self.archive.cleanup_temp_dir(previous)
        self.files, self.audio, self.sample_rate = files, loaded, rate
        self.processed = None
        self.onsets = self.targets = np.array([], dtype=int)
        return [Path(p).name for p in files]

    def quantize(self, reference, enabled, bpm, grid, strength):
        names = [Path(p).name for p in self.files]
        if not self.audio or reference not in names:
            raise ValueError("먼저 분석하고 기준 트랙을 선택하세요.")
        if not np.isfinite(bpm) or not 40 <= bpm <= 300:
            raise ValueError("BPM은 40–300 범위여야 합니다.")
        if not np.isfinite(strength) or not 0 <= strength <= 100:
            raise ValueError("강도는 0–100 범위여야 합니다.")
        if not enabled or any(name not in names for name in enabled):
            raise ValueError("적용할 트랙을 한 개 이상 선택하세요.")
        ref = self.audio[names.index(reference)]
        onsets = TransientDetector.detect_onsets(
            ref, self.sample_rate, refine_to_zero_crossing=False
        )
        onsets = np.unique(np.asarray(onsets, dtype=int))
        onsets = onsets[(onsets >= 0) & (onsets < len(ref))]
        interval = Quantizer._calculate_grid_interval(bpm, grid, self.sample_rate)
        points = Quantizer._generate_grid_points(len(ref), interval)
        targets = Quantizer._quantize_onsets(onsets, points, strength / 100)
        result = []
        for name, audio in zip(names, self.audio):
            if name not in enabled:
                result.append(audio.copy())
            else:
                result.append(
                    Quantizer._slice_and_reassemble(
                        audio, onsets, targets, self.sample_rate, 5
                    )
                )
        self.onsets, self.targets, self.processed = onsets, targets, result
        return {
            "hits": len(onsets),
            "mean_shift_samples": float(np.mean(np.abs(targets - onsets)))
            if len(onsets)
            else 0.0,
            "max_shift_samples": int(np.max(np.abs(targets - onsets)))
            if len(onsets)
            else 0,
            "enabled": list(enabled),
            "reference": reference,
        }

    def export(self):
        if self.processed is None:
            raise ValueError("먼저 그룹 처리를 완료하세요.")
        directory = self.root / ("export-" + uuid.uuid4().hex)
        directory.mkdir(mode=0o700)
        paths = []
        for index, (filename, audio) in enumerate(zip(self.files, self.processed), 1):
            path = directory / (
                f"{index:02d}_" + Path(filename).stem + "_quantized.wav"
            )
            sf.write(path, audio, self.sample_rate, format="WAV", subtype="FLOAT")
            paths.append(str(path))
        archive = directory / "drum-quanta-tracks.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for path in paths:
                output.write(path, arcname=Path(path).name)
        return [*paths, str(archive)]
