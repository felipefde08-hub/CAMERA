from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from typing import Any

import cv2

from backend.config import Settings
from backend.vision.models import BoundingBox, Detection


logger = logging.getLogger("campex.vision.detector")


class DetectorUnavailable(RuntimeError):
    pass


class VisionDetector(ABC):
    name = "abstract"

    def __init__(self) -> None:
        if self.__class__ is object:
            raise TypeError("VisionDetector cannot initialize a plain object.")

    @abstractmethod
    def load(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def detect(self, frame: Any) -> tuple[list[Detection], float]:
        raise NotImplementedError

    @property
    def is_loaded(self) -> bool:
        """Whether the model has been loaded and is ready for inference."""
        return True

    @property
    @abstractmethod
    def device(self) -> str:
        raise NotImplementedError


class RFDETRDetector(VisionDetector):
    name = "RF-DETR Nano"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._model: Any | None = None
        self._device = "CPU"
        self._class_names: list[str] | None = None
        self._load_lock = threading.Lock()
        self._loading = False

    @property
    def device(self) -> str:
        return self._device

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            # Double-check after acquiring lock in case another thread
            # loaded the model while we were waiting.
            if self._model is not None:
                return
            self._loading = True
        try:
            self._do_load()
        finally:
            self._loading = False

    def _do_load(self) -> None:
        logger.info("[CAMPEX][VISION] Loading RF-DETR Nano")
        requested_device = self.settings.vision_device
        try:
            import torch

            has_cuda = bool(torch.cuda.is_available())
            if requested_device == "cuda" and not has_cuda:
                logger.warning("[CAMPEX][VISION] CUDA requested but unavailable; using CPU")
            self._device = "CUDA" if requested_device in {"auto", "cuda"} and has_cuda else "CPU"
        except Exception:
            self._device = "CPU"

        try:
            from rfdetr import RFDETRNano
        except Exception as exc:
            raise DetectorUnavailable(
                "RF-DETR package is not available. Install the optional rfdetr dependency."
            ) from exc

        try:
            self._model = RFDETRNano()
            self._class_names = list(getattr(self._model, "class_names", []) or [])
            logger.info(
                "[CAMPEX][VISION] Detector ready | Device: %s | Classes: %d",
                self._device,
                len(self._class_names),
            )
        except Exception as exc:
            self._model = None
            raise DetectorUnavailable(f"RF-DETR Nano could not load: {exc}") from exc

    def detect(self, frame: Any) -> tuple[list[Detection], float]:
        self.load()
        if self._model is None:
            raise DetectorUnavailable("RF-DETR Nano is not loaded.")

        started = time.perf_counter()
        rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        raw_result = self._model.predict(rgb_frame, threshold=self.settings.vision_confidence)
        inference_ms = (time.perf_counter() - started) * 1000
        return normalize_rfdetr_result(
            raw_result, self.settings.vision_confidence, self._class_names
        ), inference_ms


def normalize_rfdetr_result(
    raw_result: Any,
    confidence_threshold: float,
    class_names: list[str] | dict[int, str] | None = None,
) -> list[Detection]:
    detections: list[Detection] = []

    xyxy = getattr(raw_result, "xyxy", None)
    confidence = getattr(raw_result, "confidence", None)
    class_names_attr = getattr(raw_result, "class_name", None)
    class_ids = getattr(raw_result, "class_id", None)

    data = getattr(raw_result, "data", None) or {}
    if isinstance(data, dict):
        if xyxy is None:
            xyxy = _first_present(data, "xyxy", "boxes")
        if confidence is None:
            confidence = _first_present(data, "confidence", "scores")
        if class_names_attr is None:
            class_names_attr = _first_present(data, "class_name", "names")
        if class_ids is None:
            class_ids = _first_present(data, "class_id", "labels")

    if xyxy is None and isinstance(raw_result, dict):
        xyxy = _first_present(raw_result, "xyxy", "boxes")
        confidence = _first_present(raw_result, "confidence", "scores")
        class_names_attr = _first_present(raw_result, "class_name", "names")
        class_ids = _first_present(raw_result, "class_id", "labels")

    if xyxy is None:
        return detections

    for index, box in enumerate(list(xyxy)):
        score = (
            round(float(confidence[index]), 6)
            if confidence is not None and index < len(confidence)
            else 0.0
        )
        if score < confidence_threshold:
            continue

        class_name = _resolve_class_name(
            class_names_attr, class_ids, index, class_names
        )

        x1, y1, x2, y2 = [float(value) for value in list(box)[:4]]
        detections.append(
            Detection(
                class_name=class_name.lower(),
                confidence=score,
                bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
            )
        )

    return detections


def _resolve_class_name(
    class_names_attr: Any,
    class_ids: Any,
    index: int,
    class_names: list[str] | dict[int, str] | None,
) -> str:
    if class_names_attr is not None:
        try:
            return str(class_names_attr[index])
        except (IndexError, TypeError):
            pass

    if class_ids is not None:
        try:
            cid = int(class_ids[index])
        except (IndexError, ValueError, TypeError):
            return "object"
        if class_names is not None:
            if isinstance(class_names, dict):
                return class_names.get(cid, str(cid))
            try:
                return class_names[cid]
            except (IndexError, TypeError):
                pass
        return str(cid)

    return "object"


def _first_present(mapping: dict, *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def create_detector(settings: Settings) -> VisionDetector:
    if settings.vision_detector != "rfdetr":
        raise DetectorUnavailable(f"Unsupported detector: {settings.vision_detector}")
    return RFDETRDetector(settings)
