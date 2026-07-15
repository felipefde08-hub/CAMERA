from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Iterator

import cv2


@dataclass(frozen=True)
class StreamConfig:
    camera_id: str
    source: str | int
    reconnect_seconds: float = 5.0


class StreamReader:
    def __init__(self, config: StreamConfig) -> None:
        self.config = config
        self.capture: cv2.VideoCapture | None = None

    def open(self) -> bool:
        source = self.config.source
        if isinstance(source, str) and source.lower().startswith(("rtsp://", "rtsps://")):
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")
            self.capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        else:
            self.capture = cv2.VideoCapture(source)
        return bool(self.capture and self.capture.isOpened())

    def close(self) -> None:
        if self.capture is not None:
            self.capture.release()
        self.capture = None

    def frames(self) -> Iterator[object]:
        while True:
            if self.capture is None or not self.capture.isOpened():
                self.close()
                if not self.open():
                    time.sleep(self.config.reconnect_seconds)
                    continue

            ok, frame = self.capture.read()
            if ok and frame is not None:
                yield frame
                continue

            self.close()
            time.sleep(self.config.reconnect_seconds)

