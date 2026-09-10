from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import cv2
import numpy as np

logger = logging.getLogger("campex.vision.motion")


@dataclass(frozen=True)
class MotionResult:
    motion_detected: bool
    motion_pixels: int
    motion_ratio: float
    regions: list[tuple[int, int, int, int]] = field(default_factory=list)


class MotionDetector:
    """Lightweight OpenCV-based motion detector.

    Uses grayscale conversion, Gaussian blur, and frame differencing
    to detect scene changes at low computational cost.  This serves as
    a cheap pre-trigger for the Vision scheduler — full object detection
    is skipped when no motion is present, conserving CPU/GPU.
    """

    def __init__(
        self,
        resize_width: int = 64,
        blur_size: int = 3,
        motion_threshold: float = 0.015,
        minimum_motion_pixels: int = 50,
    ) -> None:
        self._resize_width = resize_width
        self._blur_size = blur_size
        self._motion_threshold = motion_threshold
        self._minimum_motion_pixels = minimum_motion_pixels
        self._previous_frame: np.ndarray | None = None

    def detect(self, frame: Any) -> MotionResult:
        small = self._preprocess(frame)
        if small is None:
            return MotionResult(False, 0, 0.0)

        if self._previous_frame is None:
            self._previous_frame = small
            return MotionResult(False, 0, 0.0)

        diff = cv2.absdiff(small, self._previous_frame)
        self._previous_frame = small
        _, thresh = cv2.threshold(diff, 25, 255, cv2.THRESH_BINARY)
        motion_pixels = int(cv2.countNonZero(thresh))
        total_pixels = thresh.shape[0] * thresh.shape[1]
        ratio = motion_pixels / total_pixels if total_pixels else 0.0

        motion_detected = (
            ratio >= self._motion_threshold
            and motion_pixels >= self._minimum_motion_pixels
        )

        regions = self._extract_regions(thresh) if motion_detected else []

        if motion_detected:
            logger.debug(
                "Motion detected",
                extra={"motion_pixels": motion_pixels, "motion_ratio": round(ratio, 4)},
            )

        return MotionResult(motion_detected, motion_pixels, ratio, regions)

    @property
    def has_reference(self) -> bool:
        return self._previous_frame is not None

    def reset(self) -> None:
        self._previous_frame = None

    def _preprocess(self, frame: Any) -> np.ndarray | None:
        if frame is None:
            return None
        try:
            height = frame.shape[0]
            aspect = self._resize_width / max(1, frame.shape[1])
            new_height = max(1, int(height * aspect))
            resized = cv2.resize(frame, (self._resize_width, new_height))
            gray = cv2.cvtColor(resized, cv2.COLOR_BGR2GRAY)
            return cv2.GaussianBlur(gray, (self._blur_size, self._blur_size), 0)
        except Exception:
            return None

    @staticmethod
    def _extract_regions(thresh: np.ndarray) -> list[tuple[int, int, int, int]]:
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        regions: list[tuple[int, int, int, int]] = []
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 50:
                continue
            x, y, w, h = cv2.boundingRect(contour)
            regions.append((int(x), int(y), int(x + w), int(y + h)))
        return regions
