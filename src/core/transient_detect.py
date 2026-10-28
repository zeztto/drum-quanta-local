"""
Transient detection module for Drum Quanta
Detects drum hits with zero-crossing refinement for clean cuts
"""

import librosa
import numpy as np

from ..utils.config import Config


class TransientDetector:
    """Detect transients (drum hits) with zero-crossing refinement"""

    @staticmethod
    def detect_onsets(
        audio: np.ndarray,
        sr: int,
        threshold: float | None = None,
        min_distance_ms: float | None = None,
        refine_to_zero_crossing: bool = True,
        zero_crossing_window_ms: float = 5.0,
    ) -> np.ndarray:
        """
        Detect onset positions in audio with zero-crossing refinement

        Args:
            audio: Input audio
            sr: Sample rate
            threshold: Detection threshold (0.0-1.0)
            min_distance_ms: Minimum distance between onsets (ms)
            refine_to_zero_crossing: Refine onsets to nearest zero crossing
            zero_crossing_window_ms: Search window for zero crossing (ms)

        Returns:
            Array of onset positions (in samples)
        """
        if threshold is None:
            threshold = Config.TRANSIENT_DEFAULT_THRESHOLD

        if min_distance_ms is None:
            min_distance_ms = Config.TRANSIENT_MIN_DISTANCE_MS

        # Convert min distance to samples
        min_distance_samples = int((min_distance_ms / 1000.0) * sr)

        # Detect onsets using librosa with safer parameters
        onset_strength = librosa.onset.onset_strength(y=audio, sr=sr)

        # Use simpler peak picking without backtracking
        # This avoids numpy compatibility issues

        # Calculate detection threshold (use threshold parameter as relative value)
        detection_threshold = (
            threshold * onset_strength.max() if onset_strength.max() > 0 else 0.01
        )

        try:
            onset_frames = librosa.onset.onset_detect(
                onset_envelope=onset_strength,
                sr=sr,
                backtrack=False,
                normalize=False,  # delta is in the unnormalized envelope units
                delta=detection_threshold,
                wait=1,  # Minimum frames between onsets
                pre_max=1,
                post_max=1,
            )
        except (ValueError, RuntimeError, librosa.util.exceptions.ParameterError):
            # Fallback: manual peak picking
            onset_frames = TransientDetector._simple_peak_picking(
                onset_strength, threshold=detection_threshold
            )

        # If no onsets detected, return empty array
        if len(onset_frames) == 0:
            return np.array([])

        # Convert frames to samples
        onsets = librosa.frames_to_samples(onset_frames)

        # Apply minimum distance filter
        if len(onsets) > 0 and min_distance_samples > 0:
            onsets = TransientDetector._filter_by_min_distance(
                onsets, min_distance_samples
            )

        # Refine to zero crossings for clean cuts
        if refine_to_zero_crossing and len(onsets) > 0:
            zero_crossing_window = int((zero_crossing_window_ms / 1000.0) * sr)
            onsets = TransientDetector._refine_to_zero_crossings(
                audio, onsets, zero_crossing_window
            )

        return onsets

    @staticmethod
    def _filter_by_min_distance(onsets: np.ndarray, min_distance: int) -> np.ndarray:
        """
        Filter onsets by minimum distance, keeping strongest peaks

        Args:
            onsets: Onset positions
            min_distance: Minimum distance in samples

        Returns:
            Filtered onsets
        """
        if len(onsets) <= 1:
            return onsets

        filtered = [onsets[0]]

        for onset in onsets[1:]:
            if onset - filtered[-1] >= min_distance:
                filtered.append(onset)

        return np.array(filtered)

    @staticmethod
    def _refine_to_zero_crossings(
        audio: np.ndarray, onsets: np.ndarray, window_size: int
    ) -> np.ndarray:
        """
        Refine onset positions to nearest zero crossing for click-free cuts

        Args:
            audio: Input audio
            onsets: Initial onset positions
            window_size: Search window size (samples)

        Returns:
            Refined onset positions
        """
        refined_onsets = []

        for onset in onsets:
            # Define search window (look backwards from onset)
            start = max(0, onset - window_size)
            end = min(len(audio), onset + window_size // 4)  # Smaller forward search

            if start >= end:
                refined_onsets.append(onset)
                continue

            # Find zero crossings in window
            window = audio[start:end]
            zero_crossings = TransientDetector._find_zero_crossings(window)

            if len(zero_crossings) == 0:
                # No zero crossing found, use original onset
                refined_onsets.append(onset)
            else:
                # Find closest zero crossing to original onset
                absolute_positions = zero_crossings + start
                distances = np.abs(absolute_positions - onset)
                closest_idx = np.argmin(distances)
                refined_onsets.append(absolute_positions[closest_idx])

        return np.array(refined_onsets)

    @staticmethod
    def _find_zero_crossings(audio: np.ndarray) -> np.ndarray:
        """
        Find zero crossing positions in audio

        Args:
            audio: Input audio

        Returns:
            Array of zero crossing positions
        """
        # Find where sign changes
        signs = np.sign(audio)
        signs[signs == 0] = 1  # Treat zeros as positive

        # Zero crossings occur where sign changes
        zero_crossings = np.where(np.diff(signs))[0]

        return zero_crossings

    @staticmethod
    def estimate_tempo(onsets: np.ndarray, sr: int) -> float:
        """
        Estimate tempo from onset intervals

        Args:
            onsets: Onset positions (samples)
            sr: Sample rate

        Returns:
            Estimated BPM
        """
        if len(onsets) < 2:
            return Config.BPM_DEFAULT

        # Calculate intervals between onsets
        intervals = np.diff(onsets) / sr  # in seconds

        # Use median interval (more robust than mean)
        median_interval = np.median(intervals)

        # Assume intervals are beats or subdivisions
        # Try common subdivisions: quarter, eighth, sixteenth
        possible_bpms = [
            60.0 / median_interval,  # Quarter note
            60.0 / (median_interval * 2),  # Eighth note
            60.0 / (median_interval * 4),  # Sixteenth note
        ]

        # Choose BPM in valid range
        for bpm in possible_bpms:
            if Config.BPM_MIN <= bpm <= Config.BPM_MAX:
                return bpm

        # Fallback
        return Config.BPM_DEFAULT

    @staticmethod
    def analyze_transient_density(
        audio: np.ndarray, sr: int, threshold: float | None = None
    ) -> dict:
        """
        Analyze transient density and characteristics

        Args:
            audio: Input audio
            sr: Sample rate
            threshold: Detection threshold

        Returns:
            Dictionary with analysis results
        """
        onsets = TransientDetector.detect_onsets(
            audio, sr, threshold=threshold, refine_to_zero_crossing=False
        )

        if len(onsets) == 0:
            return {
                "count": 0,
                "density": 0.0,
                "avg_interval_ms": 0.0,
                "estimated_bpm": 0.0,
            }

        # Calculate statistics
        duration_s = len(audio) / sr
        density = len(onsets) / duration_s  # transients per second

        intervals = np.diff(onsets) / sr * 1000.0  # in ms
        avg_interval = np.mean(intervals) if len(intervals) > 0 else 0.0

        estimated_bpm = TransientDetector.estimate_tempo(onsets, sr)

        return {
            "count": len(onsets),
            "density": density,
            "avg_interval_ms": avg_interval,
            "estimated_bpm": estimated_bpm,
        }

    @staticmethod
    def detect_with_confidence(
        audio: np.ndarray,
        sr: int,
        threshold: float | None = None,
        min_distance_ms: float | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """
        Detect onsets with confidence scores

        Args:
            audio: Input audio
            sr: Sample rate
            threshold: Detection threshold
            min_distance_ms: Minimum distance between onsets

        Returns:
            Tuple of (onset_positions, confidence_scores)
        """
        if threshold is None:
            threshold = Config.TRANSIENT_DEFAULT_THRESHOLD

        # Get onset strength envelope
        onset_strength = librosa.onset.onset_strength(y=audio, sr=sr)

        # Detect onsets with error handling
        try:
            onset_frames = librosa.onset.onset_detect(
                onset_envelope=onset_strength,
                sr=sr,
                backtrack=False,
                delta=threshold * onset_strength.max()
                if onset_strength.max() > 0
                else 0.1,
                wait=1,
            )
        except (ValueError, RuntimeError, librosa.util.exceptions.ParameterError):
            onset_frames = TransientDetector._simple_peak_picking(
                onset_strength,
                threshold=threshold * onset_strength.max()
                if onset_strength.max() > 0
                else 0.1,
            )

        if len(onset_frames) == 0:
            return np.array([]), np.array([])

        # Get confidence scores from onset strength
        confidence_scores = onset_strength[onset_frames]

        # Normalize confidence to 0-1 range
        if confidence_scores.max() > 0:
            confidence_scores = confidence_scores / confidence_scores.max()

        # Convert to samples
        onsets = librosa.frames_to_samples(onset_frames)

        # Apply minimum distance filter
        if min_distance_ms is not None:
            min_distance_samples = int((min_distance_ms / 1000.0) * sr)
            if min_distance_samples > 0:
                filtered_indices = (
                    TransientDetector._filter_by_min_distance_with_indices(
                        onsets, min_distance_samples
                    )
                )
                onsets = onsets[filtered_indices]
                confidence_scores = confidence_scores[filtered_indices]

        return onsets, confidence_scores

    @staticmethod
    def _filter_by_min_distance_with_indices(
        onsets: np.ndarray, min_distance: int
    ) -> list[int]:
        """
        Filter onsets by minimum distance, returning indices

        Args:
            onsets: Onset positions
            min_distance: Minimum distance in samples

        Returns:
            List of indices to keep
        """
        if len(onsets) <= 1:
            return list(range(len(onsets)))

        keep_indices = [0]

        for i in range(1, len(onsets)):
            if onsets[i] - onsets[keep_indices[-1]] >= min_distance:
                keep_indices.append(i)

        return keep_indices

    @staticmethod
    def _simple_peak_picking(
        onset_strength: np.ndarray, threshold: float
    ) -> np.ndarray:
        """
        Simple peak picking as fallback when librosa fails

        Args:
            onset_strength: Onset strength envelope
            threshold: Detection threshold

        Returns:
            Array of peak positions (frames)
        """
        peaks = []

        # Find local maxima above threshold
        for i in range(1, len(onset_strength) - 1):
            # Check if this is a local maximum
            if (
                onset_strength[i] > threshold
                and onset_strength[i] > onset_strength[i - 1]
                and onset_strength[i] > onset_strength[i + 1]
            ):
                peaks.append(i)

        return np.array(peaks)
