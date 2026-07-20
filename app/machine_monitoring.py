from __future__ import annotations

import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.config import ROOT
from app.database import connect, init_db
from app.models import (
    atualizar_evento_machine_stoppage,
    atualizar_evento_replay,
    atualizar_machine_monitor_estado,
    criar_evento_machine_stoppage,
    fechar_evento_machine_stoppage,
)
from app.person_detection import Detection
from app.restricted_area import AreaPoint, foot_point_normalized, normalize_points, point_in_polygon
from app.security import mask_sensitive_error
from shared.schemas import now_iso


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


@dataclass
class MachineMonitorConfig:
    id: str
    client_id: str
    unit_id: str
    camera_id: str
    nome: str
    machine_polygon: list[AreaPoint]
    operator_polygon: list[AreaPoint]
    ativo: bool = True
    motion_sensitivity: float = 25.0
    motion_threshold: float | None = None
    stop_seconds: float = 10.0
    recovery_seconds: float = 3.0
    replay_pre_seconds: float = 60.0
    replay_post_seconds: float = 30.0


@dataclass
class MachineMonitorState:
    state: str = "unavailable"
    motion: float = 0.0
    smoothed_motion: float = 0.0
    threshold: float = 25.0
    operator_present: bool = False
    operator_present_seconds: float = 0.0
    operator_absent_seconds: float = 0.0
    max_people: int = 0
    track_ids: set[int] = field(default_factory=set)
    event_id: str | None = None
    event_started_at: str | None = None
    state_since: float = field(default_factory=time.monotonic)
    suspected_since: float | None = None
    recovered_since: float | None = None
    last_update: float = field(default_factory=time.monotonic)


def config_from_dict(payload: dict[str, Any]) -> MachineMonitorConfig:
    return MachineMonitorConfig(
        id=str(payload["id"]),
        client_id=str(payload["client_id"]),
        unit_id=str(payload["unit_id"]),
        camera_id=str(payload["camera_id"]),
        nome=str(payload["nome"]),
        machine_polygon=[AreaPoint(float(p["x"]), float(p["y"])) for p in payload["machine_polygon"]],
        operator_polygon=[AreaPoint(float(p["x"]), float(p["y"])) for p in payload["operator_polygon"]],
        ativo=bool(payload.get("ativo", True)),
        motion_sensitivity=float(payload.get("motion_sensitivity") or 25.0),
        motion_threshold=payload.get("motion_threshold"),
        stop_seconds=float(payload.get("stop_seconds") or env_float("CAMPEX_MACHINE_STOP_SECONDS", 10.0)),
        recovery_seconds=float(payload.get("recovery_seconds") or env_float("CAMPEX_MACHINE_RECOVERY_SECONDS", 3.0)),
        replay_pre_seconds=float(payload.get("replay_pre_seconds") or env_float("CAMPEX_REPLAY_PRE_SECONDS", 60.0)),
        replay_post_seconds=float(payload.get("replay_post_seconds") or env_float("CAMPEX_REPLAY_POST_SECONDS", 30.0)),
    )


class ReplayBuffer:
    def __init__(self, camera_id: str, fps: float | None = None, max_width: int | None = None) -> None:
        self.camera_id = camera_id
        self.fps = fps if fps is not None else env_float("CAMPEX_REPLAY_FPS", 5.0)
        self.max_width = int(max_width or env_float("CAMPEX_REPLAY_MAX_WIDTH", 1280))
        self._frames: deque[tuple[float, np.ndarray, str, bool]] = deque()
        self._last_add = 0.0

    def add(self, frame: np.ndarray, state: str, operator_present: bool, keep_seconds: float) -> None:
        now = time.monotonic()
        if now - self._last_add < 1.0 / max(0.1, self.fps):
            return
        self._last_add = now
        resized = self._resize(frame)
        self._frames.append((now, resized, state, operator_present))
        cutoff = now - max(keep_seconds, 1.0)
        while self._frames and self._frames[0][0] < cutoff:
            self._frames.popleft()

    def snapshot(self, since_seconds: float | None = None) -> list[tuple[float, np.ndarray, str, bool]]:
        now = time.monotonic()
        frames = list(self._frames)
        if since_seconds is not None:
            frames = [item for item in frames if item[0] >= now - since_seconds]
        return [(ts, frame.copy(), state, present) for ts, frame, state, present in frames]

    def _resize(self, frame: np.ndarray) -> np.ndarray:
        height, width = frame.shape[:2]
        if width <= self.max_width:
            return frame.copy()
        scale = self.max_width / width
        return cv2.resize(frame, (self.max_width, int(height * scale)))


class MachineMonitorEngine:
    def __init__(self, config: MachineMonitorConfig, replay_buffer: ReplayBuffer | None = None) -> None:
        self.config = config
        self.state = MachineMonitorState(threshold=float(config.motion_threshold or config.motion_sensitivity))
        self.replay_buffer = replay_buffer or ReplayBuffer(config.camera_id)
        self.analysis_fps = env_float("CAMPEX_MACHINE_ANALYSIS_FPS", 5.0)
        self.smoothing_seconds = env_float("CAMPEX_MACHINE_MOTION_SMOOTHING_SECONDS", 2.0)
        self._last_analysis = 0.0
        self._previous_gray: np.ndarray | None = None
        self._post_frames: list[tuple[float, np.ndarray, str, bool]] | None = None
        self._event_frames: list[tuple[float, np.ndarray, str, bool]] = []

    def update(self, frame: np.ndarray, detections: list[Detection]) -> MachineMonitorState:
        now = time.monotonic()
        self.replay_buffer.add(frame, self.state.state, self.state.operator_present, self.config.replay_pre_seconds + self.config.replay_post_seconds + self.config.stop_seconds)
        if now - self._last_analysis < 1.0 / max(0.1, self.analysis_fps):
            return self.state
        dt = max(0.001, now - self.state.last_update)
        self._last_analysis = now
        self.state.last_update = now
        motion = self._motion(frame)
        self.state.motion = motion
        alpha = min(1.0, dt / max(0.1, self.smoothing_seconds))
        self.state.smoothed_motion = (alpha * motion) + ((1 - alpha) * self.state.smoothed_motion)
        self._update_operator(frame, detections, dt)
        self._transition(now, frame)
        return self.state

    def _motion(self, frame: np.ndarray) -> float:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mask = polygon_mask(gray.shape, self.config.machine_polygon)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        if self._previous_gray is None:
            self._previous_gray = gray
            return 0.0
        diff = cv2.absdiff(gray, self._previous_gray)
        self._previous_gray = gray
        values = diff[mask > 0]
        return float(np.mean(values)) if values.size else 0.0

    def _update_operator(self, frame: np.ndarray, detections: list[Detection], dt: float) -> None:
        height, width = frame.shape[:2]
        ids: set[int] = set()
        for detection in detections:
            if detection.track_id is None:
                continue
            if point_in_polygon(foot_point_normalized(detection, width, height), self.config.operator_polygon):
                ids.add(detection.track_id)
        self.state.operator_present = bool(ids)
        self.state.track_ids.update(ids)
        self.state.max_people = max(self.state.max_people, len(ids))
        if self.state.event_id:
            if ids:
                self.state.operator_present_seconds += dt
            else:
                self.state.operator_absent_seconds += dt

    def _transition(self, now: float, frame: np.ndarray) -> None:
        threshold = self.state.threshold
        low = self.state.smoothed_motion < threshold
        high = self.state.smoothed_motion >= threshold * 1.2
        previous = self.state.state
        if self.state.state in {"unavailable", "running", "recovered"}:
            if low:
                self.state.suspected_since = self.state.suspected_since or now
                self.state.state = "suspected_stop"
                if now - self.state.suspected_since >= self.config.stop_seconds:
                    self._open_event(now, frame)
            else:
                self.state.state = "running"
                self.state.suspected_since = None
        elif self.state.state == "suspected_stop":
            if not low:
                self.state.state = "running"
                self.state.suspected_since = None
            elif self.state.suspected_since and now - self.state.suspected_since >= self.config.stop_seconds:
                self._open_event(now, frame)
        elif self.state.state == "stopped":
            self._update_event(now)
            if high:
                self.state.recovered_since = self.state.recovered_since or now
                if now - self.state.recovered_since >= self.config.recovery_seconds:
                    self._close_event(now)
                    self.state.state = "recovered"
                    self._schedule_replay()
            else:
                self.state.recovered_since = None
        if previous != self.state.state:
            self.state.state_since = now
            self._persist_state(changed=True)
        else:
            self._persist_state(changed=False)

    def _open_event(self, now: float, frame: np.ndarray) -> None:
        if self.state.event_id:
            return
        self.state.state = "stopped"
        self.state.event_started_at = now_iso()
        self.state.operator_present_seconds = 0.0
        self.state.operator_absent_seconds = 0.0
        self.state.max_people = 1 if self.state.operator_present else 0
        self.state.track_ids = set(self.state.track_ids)
        image_path, error = save_machine_evidence(frame, self.config, self.state)
        with connect() as connection:
            init_db(connection)
            event_id = criar_evento_machine_stoppage(
                connection,
                cliente_id=self.config.client_id,
                unidade_id=self.config.unit_id,
                camera_id=self.config.camera_id,
                machine_monitor_id=self.config.id,
                inicio=self.state.event_started_at,
                motion_level=self.state.smoothed_motion,
                operator_present_start=self.state.operator_present,
                confidence=confidence_from_motion(self.state.smoothed_motion, self.state.threshold),
                midia_path=image_path,
                track_ids=sorted(self.state.track_ids),
            )
            if error:
                atualizar_evento_replay(connection, event_id, replay_error=error)
        self.state.event_id = event_id
        self._event_frames = self.replay_buffer.snapshot(self.config.replay_pre_seconds)

    def _update_event(self, now: float) -> None:
        if not self.state.event_id or not self.state.event_started_at:
            return
        duration = max(0.0, now - self.state.state_since)
        if int(now) % 2 != 0:
            return
        with connect() as connection:
            init_db(connection)
            atualizar_evento_machine_stoppage(
                connection,
                self.state.event_id,
                duracao=duration,
                motion_level=self.state.smoothed_motion,
                operator_present_seconds=self.state.operator_present_seconds,
                operator_absent_seconds=self.state.operator_absent_seconds,
                max_people=self.state.max_people,
                track_ids=sorted(self.state.track_ids),
            )

    def _close_event(self, now: float) -> None:
        if not self.state.event_id:
            return
        duration = max(0.0, now - self.state.state_since)
        with connect() as connection:
            init_db(connection)
            fechar_evento_machine_stoppage(connection, self.state.event_id, now_iso(), duration)

    def _schedule_replay(self) -> None:
        event_id = self.state.event_id
        if not event_id:
            return
        frames = self._event_frames + self.replay_buffer.snapshot(self.config.replay_post_seconds)
        config = self.config
        threading.Thread(target=write_replay, args=(event_id, config, frames), daemon=True).start()
        self.state.event_id = None
        self.state.event_started_at = None
        self._event_frames = []

    def _persist_state(self, changed: bool) -> None:
        try:
            with connect() as connection:
                init_db(connection)
                atualizar_machine_monitor_estado(
                    connection,
                    self.config.id,
                    self.state.state,
                    self.state.smoothed_motion,
                    self.state.operator_present,
                    now_iso() if changed else None,
                )
        except Exception:
            pass


def polygon_mask(shape: tuple[int, int], polygon: list[AreaPoint]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    pts = np.array([[int(point.x * width), int(point.y * height)] for point in polygon], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def confidence_from_motion(motion: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.5
    return round(min(0.99, max(0.5, 1.0 - (motion / max(threshold, 1e-9)) * 0.5)), 3)


def save_machine_evidence(frame: np.ndarray, config: MachineMonitorConfig, state: MachineMonitorState) -> tuple[str | None, str | None]:
    try:
        now = datetime.now(timezone.utc).astimezone()
        folder = ROOT / "data" / "evidence" / config.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now:%H%M%S}_{config.id}_machine.jpg"
        annotated = draw_machine_overlay(frame, config, state)
        if not cv2.imwrite(str(path), annotated):
            return None, "Falha ao gravar evidencia da parada."
        return str(path.relative_to(ROOT)), None
    except Exception as exc:
        return None, mask_sensitive_error(str(exc))


def write_replay(event_id: str, config: MachineMonitorConfig, frames: list[tuple[float, np.ndarray, str, bool]]) -> None:
    try:
        if not frames:
            raise RuntimeError("Sem frames para Replay Causal.")
        now = datetime.now(timezone.utc).astimezone()
        folder = ROOT / "data" / "replays" / config.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now:%H%M%S}_{config.id}_{event_id}.mp4"
        height, width = frames[0][1].shape[:2]
        writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), env_float("CAMPEX_REPLAY_FPS", 5.0), (width, height))
        if not writer.isOpened():
            raise RuntimeError("Nao foi possivel iniciar gravacao do replay.")
        for _ts, frame, state, operator_present in frames:
            annotated = draw_machine_overlay(frame, config, MachineMonitorState(state=state, operator_present=operator_present))
            writer.write(annotated)
        writer.release()
        with connect() as connection:
            init_db(connection)
            atualizar_evento_replay(connection, event_id, replay_path=str(path.relative_to(ROOT)), replay_error=None)
    except Exception as exc:
        with connect() as connection:
            init_db(connection)
            atualizar_evento_replay(connection, event_id, replay_error=mask_sensitive_error(str(exc)))


def draw_machine_overlay(frame: np.ndarray, config: MachineMonitorConfig, state: MachineMonitorState) -> np.ndarray:
    annotated = frame.copy()
    height, width = annotated.shape[:2]
    for polygon, color in ((config.machine_polygon, (255, 180, 0)), (config.operator_polygon, (0, 220, 255))):
        pts = np.array([[int(point.x * width), int(point.y * height)] for point in polygon], dtype=np.int32)
        cv2.polylines(annotated, [pts], True, color, 2)
    label = f"Campex | {config.nome} | {state.state} | operador: {'presente' if state.operator_present else 'ausente'}"
    cv2.putText(annotated, label, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 4, cv2.LINE_AA)
    cv2.putText(annotated, label, (16, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (0, 0, 0), 2, cv2.LINE_AA)
    return annotated


def calibrate_threshold(running_motion: float, stopped_motion: float) -> float:
    return round((float(running_motion) + float(stopped_motion)) / 2.0, 3)
