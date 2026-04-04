from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

_log = logging.getLogger(__name__)


@dataclass(slots=True)
class GifSettings:
    fps: int = 15
    width: int = 480
    quality: int = 80
    start_sec: float = 0.0
    end_sec: float = 0.0  # 0 = full duration


@dataclass(slots=True)
class ConversionResult:
    success: bool
    output_path: str
    file_size: int
    frame_count: int
    message: str


def get_video_duration(path: str) -> float:
    """Return video duration in seconds."""
    try:
        import imageio.v3 as iio

        meta = iio.immeta(path, plugin="pyav")
        return float(meta.get("duration", 0))
    except Exception:
        try:
            import imageio.v3 as iio

            meta = iio.improps(path, plugin="pyav")
            return float(getattr(meta, "n_images", 0)) / 30.0
        except Exception:
            return 0.0


def convert_video_to_gif(
    input_path: str,
    output_path: str,
    settings: GifSettings,
    progress: Callable[[int, int], None] | None = None,
) -> ConversionResult:
    """Convert a video file to GIF.

    Args:
        input_path: Path to source video
        output_path: Path for output GIF
        settings: Conversion settings (fps, width, quality, start/end)
        progress: Callback (current_frame, total_frames)

    Returns:
        ConversionResult with success flag and details
    """
    try:
        import imageio.v3 as iio
        import numpy as np
    except ImportError as exc:
        return ConversionResult(False, "", 0, 0, f"Missing dependency: {exc}")

    try:
        # Read all frames
        frames_raw = iio.imread(input_path, plugin="pyav")
        total_raw = len(frames_raw)

        if total_raw == 0:
            return ConversionResult(False, "", 0, 0, "Video has no frames")

        # Get source FPS from metadata
        try:
            meta = iio.immeta(input_path, plugin="pyav")
            src_fps = float(meta.get("fps", 30))
        except Exception:
            src_fps = 30.0

        # Apply start/end trim
        start_frame = int(settings.start_sec * src_fps) if settings.start_sec > 0 else 0
        end_frame = int(settings.end_sec * src_fps) if settings.end_sec > 0 else total_raw
        start_frame = max(0, min(start_frame, total_raw - 1))
        end_frame = max(start_frame + 1, min(end_frame, total_raw))

        frames_trimmed = frames_raw[start_frame:end_frame]

        # Sample frames at target FPS
        step = max(1, int(src_fps / settings.fps))
        frames_sampled = frames_trimmed[::step]

        # Resize frames
        resized_frames = []
        for i, frame in enumerate(frames_sampled):
            h, w = frame.shape[:2]
            if w > settings.width:
                scale = settings.width / w
                new_h = int(h * scale)
                new_w = settings.width
                # Simple resize using numpy slicing
                from PIL import Image

                img = Image.fromarray(frame)
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                frame = np.array(img)
            resized_frames.append(frame)
            if progress:
                progress(i + 1, len(frames_sampled))

        if not resized_frames:
            return ConversionResult(False, "", 0, 0, "No frames after processing")

        # Write GIF
        # Map quality (1-100) to quantize colors and loop
        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)

        duration_ms = 1000 / settings.fps
        iio.imwrite(
            str(out),
            resized_frames,
            duration=duration_ms,
            loop=0,
            plugin="pillow",
        )

        file_size = out.stat().st_size
        return ConversionResult(
            True, str(out), file_size, len(resized_frames), "OK"
        )

    except Exception as exc:
        _log.exception("GIF conversion failed")
        return ConversionResult(False, "", 0, 0, str(exc))


class VideoToGifService:
    """Threaded wrapper for video-to-GIF conversion."""

    def __init__(self) -> None:
        self._thread: threading.Thread | None = None
        self._result: ConversionResult | None = None
        self._progress: tuple[int, int] = (0, 0)
        self._running = False

    @property
    def running(self) -> bool:
        return self._running

    @property
    def progress(self) -> tuple[int, int]:
        return self._progress

    @property
    def result(self) -> ConversionResult | None:
        return self._result

    def start(
        self,
        input_path: str,
        output_path: str,
        settings: GifSettings,
    ) -> None:
        if self._running:
            return
        self._result = None
        self._progress = (0, 0)
        self._running = True

        def _worker() -> None:
            try:
                self._result = convert_video_to_gif(
                    input_path, output_path, settings, self._on_progress
                )
            except Exception as exc:
                self._result = ConversionResult(False, "", 0, 0, str(exc))
            finally:
                self._running = False

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def _on_progress(self, current: int, total: int) -> None:
        self._progress = (current, total)
