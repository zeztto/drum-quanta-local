"""
Quantization engine for Drum Quanta
Slices audio using a supplied onset plan and weighted overlap envelopes
"""

import numpy as np

from ..utils.config import Config


class Quantizer:
    """
    Quantize using the supplied onset plan

    Key features:
    - Weighted crossfading at edit boundaries
    - Caller-supplied cut locations
    - Adjustable quantization strength (0-100%)
    - No automatic gain normalization
    """

    @staticmethod
    def quantize(
        audio: np.ndarray,
        onsets: np.ndarray,
        bpm: float,
        grid_division: str,
        sr: int,
        strength: float = 0.8,
        crossfade_ms: float | None = None,
    ) -> np.ndarray:
        """
        Quantize audio to rhythmic grid

        Args:
            audio: Input audio
            onsets: Onset positions (samples)
            bpm: Beats per minute
            grid_division: Grid division (e.g., '1/16', '1/8T')
            sr: Sample rate
            strength: Quantization strength (0.0-1.0, where 1.0 = 100%)
            crossfade_ms: Crossfade duration in milliseconds

        Returns:
            Quantized audio
        """
        if len(onsets) == 0:
            return audio

        if crossfade_ms is None:
            crossfade_ms = Config.QUANTIZE_CROSSFADE_MS

        # Calculate grid interval
        grid_interval_samples = Quantizer._calculate_grid_interval(
            bpm, grid_division, sr
        )

        # Generate grid points
        grid_points = Quantizer._generate_grid_points(len(audio), grid_interval_samples)

        # Quantize onset positions based on strength
        quantized_onsets = Quantizer._quantize_onsets(onsets, grid_points, strength)

        # Slice and reassemble audio
        quantized_audio = Quantizer._slice_and_reassemble(
            audio, onsets, quantized_onsets, sr, crossfade_ms
        )

        return quantized_audio

    @staticmethod
    def _calculate_grid_interval(bpm: float, grid_division: str, sr: int) -> int:
        """
        Calculate grid interval in samples

        Args:
            bpm: Beats per minute
            grid_division: Grid division
            sr: Sample rate

        Returns:
            Grid interval in samples
        """
        grid_interval_seconds = Config.get_grid_interval(bpm, grid_division)
        return int(grid_interval_seconds * sr)

    @staticmethod
    def _generate_grid_points(audio_length: int, grid_interval: int) -> np.ndarray:
        """
        Generate grid points across audio length

        Args:
            audio_length: Length of audio in samples
            grid_interval: Grid interval in samples

        Returns:
            Array of grid positions
        """
        num_points = int(np.ceil(audio_length / grid_interval)) + 1
        grid_points = np.arange(num_points) * grid_interval
        return grid_points

    @staticmethod
    def _quantize_onsets(
        onsets: np.ndarray, grid_points: np.ndarray, strength: float
    ) -> np.ndarray:
        """
        Quantize onset positions to grid with adjustable strength

        Args:
            onsets: Original onset positions
            grid_points: Grid positions
            strength: Quantization strength (0.0-1.0)

        Returns:
            Quantized onset positions
        """
        quantized = np.zeros_like(onsets, dtype=float)

        for i, onset in enumerate(onsets):
            # Find nearest grid point
            distances = np.abs(grid_points - onset)
            nearest_grid_idx = np.argmin(distances)
            nearest_grid = grid_points[nearest_grid_idx]

            # Apply quantization strength
            # strength=1.0: move fully to grid
            # strength=0.0: stay at original position
            quantized[i] = onset + strength * (nearest_grid - onset)

        return quantized.astype(int)

    @staticmethod
    def _slice_and_reassemble(
        audio: np.ndarray,
        original_onsets: np.ndarray,
        quantized_onsets: np.ndarray,
        sr: int,
        crossfade_ms: float,
    ) -> np.ndarray:
        """
        Slice audio at onsets and reassemble at quantized positions

        This is the most critical function for audio quality:
        - Uses equal-power crossfading
        - No automatic gain normalizations
        - Prevents digital artifacts

        Args:
            audio: Input audio
            original_onsets: Original onset positions
            quantized_onsets: Quantized onset positions
            sr: Sample rate
            crossfade_ms: Crossfade duration (ms)

        Returns:
            Reassembled audio
        """
        if len(original_onsets) == 0:
            return audio

        if np.array_equal(original_onsets, quantized_onsets):
            return audio.copy()
        original_onsets = np.asarray(original_onsets, dtype=int)
        quantized_onsets = np.asarray(quantized_onsets, dtype=int)
        if len(original_onsets) != len(quantized_onsets) or np.any(
            quantized_onsets < 0
        ):
            raise ValueError("Invalid common cut plan")
        if original_onsets[0] > 0:
            original_onsets = np.insert(original_onsets, 0, 0)
            quantized_onsets = np.insert(quantized_onsets, 0, 0)
        crossfade_samples = int((crossfade_ms / 1000.0) * sr)

        # Create slices between onsets
        slices = []
        slice_positions = []

        for i in range(len(original_onsets)):
            # Determine slice boundaries
            start = original_onsets[i]

            if i < len(original_onsets) - 1:
                end = original_onsets[i + 1]
            else:
                # Last slice goes to end of audio
                end = len(audio)

            # Extract slice
            audio_slice = audio[start:end].copy()
            slices.append(audio_slice)

            # Quantized position for this slice
            slice_positions.append(quantized_onsets[i])

        # Calculate required output length
        last_slice_end = slice_positions[-1] + len(slices[-1])
        output_length = max(len(audio), last_slice_end)

        # Initialize output
        output = np.zeros(output_length)
        crossfade_weights = np.zeros(output_length)  # Track overlapping regions

        # Place slices with crossfading
        for i, (audio_slice, position) in enumerate(zip(slices, slice_positions)):
            slice_len = len(audio_slice)
            slice_end = position + slice_len

            # Ensure we don't exceed output bounds
            if slice_end > len(output):
                audio_slice = audio_slice[: len(output) - position]
                slice_end = len(output)
                slice_len = len(audio_slice)

            if slice_len == 0:
                continue

            # Create fade envelopes
            fade_in = np.ones(slice_len)
            fade_out = np.ones(slice_len)

            # Apply fade-in at start of slice
            if i > 0:  # Not first slice
                fade_in_len = min(crossfade_samples, slice_len)
                fade_in[:fade_in_len] = Quantizer._equal_power_fade_in(fade_in_len)

            # Apply fade-out at end of slice
            if i < len(slices) - 1:  # Not last slice
                fade_out_len = min(crossfade_samples, slice_len)
                fade_out[-fade_out_len:] = Quantizer._equal_power_fade_out(fade_out_len)

            # Combined envelope
            envelope = fade_in * fade_out

            # Add weighted slice to output
            output[position:slice_end] += audio_slice * envelope
            crossfade_weights[position:slice_end] += envelope

        # Normalize overlapping regions to maintain unity gain
        # This prevents volume dips in crossfade regions
        nonzero = crossfade_weights > 0
        output[nonzero] /= crossfade_weights[nonzero]

        # Trim to original length (or keep extended if needed)
        if len(output) > len(audio):
            # Audio was stretched, keep new length
            pass
        else:
            # Trim to original length
            output = output[: len(audio)]

        return output

    @staticmethod
    def _equal_power_fade_in(length: int) -> np.ndarray:
        """
        Generate equal-power fade-in curve

        Equal-power crossfading maintains constant energy during transition,
        preventing the "dip in the middle" problem of linear fades.

        Args:
            length: Fade length in samples

        Returns:
            Fade-in curve
        """
        # Use sine curve for equal-power fade
        # Goes from 0 to 1 using sin(x) from 0 to π/2
        t = np.linspace(0, np.pi / 2, length)
        return np.sin(t)

    @staticmethod
    def _equal_power_fade_out(length: int) -> np.ndarray:
        """
        Generate equal-power fade-out curve

        Args:
            length: Fade length in samples

        Returns:
            Fade-out curve
        """
        # Use cosine curve for equal-power fade
        # Goes from 1 to 0 using cos(x) from 0 to π/2
        t = np.linspace(0, np.pi / 2, length)
        return np.cos(t)

    @staticmethod
    def calculate_timing_adjustments(
        original_onsets: np.ndarray, quantized_onsets: np.ndarray, sr: int
    ) -> dict:
        """
        Calculate statistics about timing adjustments

        Args:
            original_onsets: Original onset positions
            quantized_onsets: Quantized onset positions
            sr: Sample rate

        Returns:
            Dictionary with adjustment statistics
        """
        if len(original_onsets) == 0:
            return {
                "count": 0,
                "avg_adjustment_ms": 0.0,
                "max_adjustment_ms": 0.0,
                "rms_adjustment_ms": 0.0,
            }

        # Calculate adjustments in milliseconds
        adjustments_samples = quantized_onsets - original_onsets
        adjustments_ms = (adjustments_samples / sr) * 1000.0

        return {
            "count": len(original_onsets),
            "avg_adjustment_ms": float(np.mean(np.abs(adjustments_ms))),
            "max_adjustment_ms": float(np.max(np.abs(adjustments_ms))),
            "rms_adjustment_ms": float(np.sqrt(np.mean(adjustments_ms**2))),
            "adjustments_ms": adjustments_ms.tolist(),
        }

    @staticmethod
    def preview_quantization(
        onsets: np.ndarray,
        bpm: float,
        grid_division: str,
        sr: int,
        strength: float = 0.8,
    ) -> tuple[np.ndarray, np.ndarray, dict]:
        """
        Preview quantization without processing audio

        Args:
            onsets: Onset positions
            bpm: Beats per minute
            grid_division: Grid division
            sr: Sample rate
            strength: Quantization strength

        Returns:
            Tuple of (original_onsets, quantized_onsets, statistics)
        """
        grid_interval = Quantizer._calculate_grid_interval(bpm, grid_division, sr)

        # Estimate audio length from onsets
        audio_length = int(onsets[-1] * 1.5) if len(onsets) > 0 else sr * 60

        grid_points = Quantizer._generate_grid_points(audio_length, grid_interval)
        quantized_onsets = Quantizer._quantize_onsets(onsets, grid_points, strength)

        stats = Quantizer.calculate_timing_adjustments(onsets, quantized_onsets, sr)

        return onsets, quantized_onsets, stats
