from __future__ import annotations

import os
import json
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from app.alerts import enqueue_event_alert
from app.config import ROOT
from app.database import connect, init_db
from app.models import (
    atualizar_evento_machine_stoppage,
    atualizar_evento_replay,
    atualizar_machine_monitor_estado,
    criar_evento_machine_operational,
    criar_evento_machine_stoppage,
    fechar_evento_machine_stoppage,
    new_id,
    registrar_evidence_index,
    registrar_operational_sample,
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
    active_baseline: float | None = None
    stopped_baseline: float | None = None
    active_noise: float | None = None
    stopped_noise: float | None = None
    operator_absence_seconds: float = 30.0
    stopped_with_operator_seconds: float = 120.0
    microstop_window_seconds: float = 3600.0
    microstop_limit: int = 5
    loss_model: str | None = None
    loss_per_minute: float | None = None
    units_per_minute: float | None = None
    margin_per_unit: float | None = None


@dataclass
class MachineMonitorState:
    state: str = "UNKNOWN"
    motion: float = 0.0
    smoothed_motion: float = 0.0
    threshold: float = 25.0
    confidence: float = 0.0
    reason: str = "monitoramento ainda sem amostras suficientes"
    operator_present: bool = False
    operator_present_seconds: float = 0.0
    operator_absent_seconds: float = 0.0
    max_people: int = 0
    track_ids: set[int] = field(default_factory=set)
    event_id: str | None = None
    event_started_at: str | None = None
    active_events: dict[str, str] = field(default_factory=dict)
    active_event_since: dict[str, float] = field(default_factory=dict)
    active_event_opened: dict[str, float] = field(default_factory=dict)
    active_event_condition_started: dict[str, float] = field(default_factory=dict)
    state_since: float = field(default_factory=time.monotonic)
    candidate_state: str | None = None
    candidate_since: float | None = None
    last_update: float = field(default_factory=time.monotonic)
    stopped_transitions: deque[float] = field(default_factory=deque)
    analysis_status: str = "WAITING_FOR_REGION"
    analysis_error: str | None = None
    frames_analyzed: int = 0
    roi_width: int = 0
    roi_height: int = 0
    raw_activity_score: float | None = None


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
        active_baseline=payload.get("active_baseline") or payload.get("running_motion"),
        stopped_baseline=payload.get("stopped_baseline") or payload.get("stopped_motion"),
        active_noise=payload.get("active_noise"),
        stopped_noise=payload.get("stopped_noise"),
        operator_absence_seconds=float(payload.get("operator_absence_seconds") or env_float("CAMPEX_OPERATOR_ABSENCE_SECONDS", 30.0)),
        stopped_with_operator_seconds=float(payload.get("stopped_with_operator_seconds") or env_float("CAMPEX_STOPPED_WITH_OPERATOR_SECONDS", 120.0)),
        microstop_window_seconds=float(payload.get("microstop_window_seconds") or env_float("CAMPEX_MICROSTOP_WINDOW_SECONDS", 3600.0)),
        microstop_limit=int(payload.get("microstop_limit") or int(env_float("CAMPEX_MICROSTOP_LIMIT", 5))),
        loss_model=payload.get("loss_model"),
        loss_per_minute=payload.get("loss_per_minute"),
        units_per_minute=payload.get("units_per_minute"),
        margin_per_unit=payload.get("margin_per_unit"),
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

    def calibrate_active(self, motions: list[float]) -> dict[str, float]:
        baseline, noise = baseline_stats(motions)
        self.config.active_baseline = baseline
        self.config.active_noise = noise
        self.config.motion_threshold = self._calculated_threshold()
        self.state.threshold = float(self.config.motion_threshold or self.state.threshold)
        self._persist_calibration("active")
        return {"active_baseline": baseline, "active_noise": noise, "motion_threshold": self.state.threshold}

    def calibrate_stopped(self, motions: list[float]) -> dict[str, float]:
        baseline, noise = baseline_stats(motions)
        self.config.stopped_baseline = baseline
        self.config.stopped_noise = noise
        self.config.motion_threshold = self._calculated_threshold()
        self.state.threshold = float(self.config.motion_threshold or self.state.threshold)
        self._persist_calibration("stopped")
        return {"stopped_baseline": baseline, "stopped_noise": noise, "motion_threshold": self.state.threshold}

    def update(self, frame: np.ndarray, detections: list[Detection]) -> MachineMonitorState:
        now = time.monotonic()
        self.replay_buffer.add(frame, self.state.state, self.state.operator_present, self.config.replay_pre_seconds + self.config.replay_post_seconds + self.config.stop_seconds)
        if now - self._last_analysis < 1.0 / max(0.1, self.analysis_fps):
            self.state.analysis_status = "FRAME_STALE"
            return self.state
        dt = max(0.001, now - self.state.last_update)
        self._last_analysis = now
        self.state.last_update = now
        try:
            motion = self._motion(frame)
        except Exception as exc:
            self.state.analysis_status = "ERROR"
            self.state.analysis_error = mask_sensitive_error(exc)
            self.state.reason = f"erro na análise visual: {self.state.analysis_error}"
            return self.state
        self.state.motion = motion
        self.state.raw_activity_score = round(float(motion), 3)
        alpha = min(1.0, dt / max(0.1, self.smoothing_seconds))
        self.state.smoothed_motion = (alpha * motion) + ((1 - alpha) * self.state.smoothed_motion)
        self._update_operator(frame, detections, dt)
        self._classify_and_transition(now, frame)
        return self.state

    def _motion(self, frame: np.ndarray) -> float:
        score, previous_gray, diagnostics = machine_activity_score(frame, self.config.machine_polygon, self._previous_gray)
        self._previous_gray = previous_gray
        self.state.analysis_status = diagnostics["analysis_status"]
        self.state.analysis_error = diagnostics.get("analysis_error")
        self.state.roi_width = int(diagnostics.get("roi_width") or 0)
        self.state.roi_height = int(diagnostics.get("roi_height") or 0)
        if score is None:
            return 0.0
        self.state.frames_analyzed += 1
        return float(score)

    def _update_operator(self, frame: np.ndarray, detections: list[Detection], dt: float) -> None:
        height, width = frame.shape[:2]
        ids: set[int] = set()
        for detection in detections:
            if detection.class_name != "person":
                continue
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

    def _classify_and_transition(self, now: float, frame: np.ndarray) -> None:
        target, confidence, reason = self._classify_state()
        previous = self.state.state
        if target != self.state.state:
            if self.state.candidate_state != target:
                self.state.candidate_state = target
                self.state.candidate_since = now
            needed = self.config.stop_seconds if target == "STOPPED" else self.config.recovery_seconds
            if self.state.candidate_since and now - self.state.candidate_since >= needed:
                self._apply_state(target, now)
        else:
            self.state.candidate_state = None
            self.state.candidate_since = None
        self.state.confidence = confidence
        self.state.reason = reason
        self._evaluate_official_events(now, frame)
        self._persist_state(changed=previous != self.state.state)

    def _classify_state(self) -> tuple[str, float, str]:
        motion = self.state.smoothed_motion
        active = self.config.active_baseline
        stopped = self.config.stopped_baseline
        if active is not None and stopped is not None and active > stopped:
            threshold = self._calculated_threshold()
            self.state.threshold = threshold
            stop_boundary = threshold
            active_boundary = threshold + max(self.config.active_noise or 0.0, self.config.stopped_noise or 0.0, 1.0) * 0.25
            if motion <= stop_boundary:
                confidence = normalized_distance(motion, stopped, active)
                return "STOPPED", confidence, f"atividade visual abaixo do baseline por janela temporal; score={motion:.2f}, limite={stop_boundary:.2f}"
            if motion >= active_boundary:
                confidence = normalized_distance(motion, active, stopped)
                return "ACTIVE", confidence, f"atividade visual proxima ao baseline ativo; score={motion:.2f}, limite={active_boundary:.2f}"
            return self.state.state if self.state.state in {"ACTIVE", "STOPPED"} else "UNKNOWN", 0.55, "atividade visual em faixa de histerese"
        threshold = float(self.config.motion_threshold or self.config.motion_sensitivity)
        self.state.threshold = threshold
        if motion >= threshold * 1.2:
            return "ACTIVE", confidence_from_active_motion(motion, threshold), f"atividade visual acima do limite configurado; score={motion:.2f}"
        if motion < threshold:
            return "STOPPED", confidence_from_motion(motion, threshold), f"atividade visual abaixo do limite configurado; score={motion:.2f}"
        return self.state.state if self.state.state in {"ACTIVE", "STOPPED"} else "UNKNOWN", 0.5, "atividade visual sem margem suficiente"

    def _apply_state(self, target: str, now: float) -> None:
        previous = self.state.state
        self.state.state = target
        self.state.state_since = now
        self.state.candidate_state = None
        self.state.candidate_since = None
        if target == "STOPPED" and previous != "STOPPED":
            self.state.stopped_transitions.append(now)
        cutoff = now - max(1.0, self.config.microstop_window_seconds)
        while self.state.stopped_transitions and self.state.stopped_transitions[0] < cutoff:
            self.state.stopped_transitions.popleft()

    def _evaluate_official_events(self, now: float, frame: np.ndarray) -> None:
        if self.state.state == "STOPPED":
            self._open_event(now, frame, "machine_stopped")
        else:
            self._close_event_type("machine_stopped", now)
        if self.state.state == "ACTIVE" and not self.state.operator_present:
            self._open_timed_event(now, frame, "machine_running_without_operator", self.config.operator_absence_seconds, "high")
        else:
            self._close_event_type("machine_running_without_operator", now)
        if self.state.state == "STOPPED" and self.state.operator_present:
            self._open_timed_event(now, frame, "machine_stopped_with_operator", self.config.stopped_with_operator_seconds, "medium")
        else:
            self._close_event_type("machine_stopped_with_operator", now)
        if len(self.state.stopped_transitions) >= self.config.microstop_limit:
            self._open_event(now, frame, "repeated_microstops", severity="medium", metadata={"microstops": len(self.state.stopped_transitions)})
        else:
            self._close_event_type("repeated_microstops", now)
        for event_type in list(self.state.active_events):
            self._update_event_type(event_type, now)

    def _open_timed_event(self, now: float, frame: np.ndarray, event_type: str, minimum_seconds: float, severity: str) -> None:
        since = self.state.active_event_since.get(event_type)
        if since is None:
            self.state.active_event_since[event_type] = now
            return
        if now - since >= minimum_seconds:
            self._open_event(now, frame, event_type, severity=severity)

    def _open_event(self, now: float, frame: np.ndarray, event_type: str = "machine_stoppage", severity: str = "medium", metadata: dict[str, Any] | None = None) -> None:
        canonical_type = "machine_stoppage" if event_type in {"machine_stopped", "machine_stoppage"} else event_type
        if self.state.active_events.get(canonical_type):
            return
        condition_started = self.state.active_event_since.get(canonical_type)
        if condition_started is None:
            condition_started = self.state.state_since if canonical_type == "machine_stoppage" else now
        if canonical_type == "machine_stoppage":
            self.state.event_started_at = self.state.event_started_at or now_iso()
        self.state.operator_present_seconds = 0.0
        self.state.operator_absent_seconds = 0.0
        self.state.max_people = 1 if self.state.operator_present else 0
        self.state.track_ids = set(self.state.track_ids)
        image_path, error = save_machine_evidence(frame, self.config, self.state)
        with connect() as connection:
            init_db(connection)
            started_at = now_iso()
            if canonical_type == "machine_stoppage":
                event_id = criar_evento_machine_stoppage(
                    connection,
                    cliente_id=self.config.client_id,
                    unidade_id=self.config.unit_id,
                    camera_id=self.config.camera_id,
                    machine_monitor_id=self.config.id,
                    inicio=started_at,
                    motion_level=self.state.smoothed_motion,
                    operator_present_start=self.state.operator_present,
                    confidence=self.state.confidence or confidence_from_motion(self.state.smoothed_motion, self.state.threshold),
                    midia_path=image_path,
                    track_ids=sorted(self.state.track_ids),
                )
            else:
                event_id = criar_evento_machine_operational(
                    connection,
                    cliente_id=self.config.client_id,
                    unidade_id=self.config.unit_id,
                    camera_id=self.config.camera_id,
                    machine_monitor_id=self.config.id,
                    tipo=canonical_type,
                    inicio=started_at,
                    motion_level=self.state.smoothed_motion,
                    operator_present_start=self.state.operator_present,
                    confidence=self.state.confidence,
                    midia_path=image_path,
                    track_ids=sorted(self.state.track_ids),
                    severidade=severity,
                    metadata={**(metadata or {}), "estimated_loss": self.estimated_loss(0), "machine_state": self.state.state},
                )
            if error:
                atualizar_evento_replay(connection, event_id, replay_error=error)
        self.state.active_events[canonical_type] = event_id
        self.state.active_event_opened[canonical_type] = now
        self.state.active_event_condition_started[canonical_type] = condition_started
        if canonical_type == "machine_stoppage":
            self.state.event_id = event_id
        self._event_frames = self.replay_buffer.snapshot(self.config.replay_pre_seconds)
        enqueue_event_alert(event_id)

    def _update_event(self, now: float) -> None:
        self._update_event_type("machine_stoppage", now)

    def _update_event_type(self, event_type: str, now: float) -> None:
        event_type = "machine_stoppage" if event_type in {"machine_stopped", "machine_stoppage"} else event_type
        event_id = self.state.active_events.get(event_type)
        if not event_id:
            return
        opened_at = self.state.active_event_opened.get(event_type)
        condition_started = self.state.active_event_condition_started.get(event_type)
        duration = max(0.0, now - (condition_started if condition_started is not None else opened_at if opened_at is not None else now))
        if int(now) % 2 != 0:
            return
        with connect() as connection:
            init_db(connection)
            atualizar_evento_machine_stoppage(
                connection,
                event_id,
                duracao=duration,
                motion_level=self.state.smoothed_motion,
                operator_present_seconds=self.state.operator_present_seconds,
                operator_absent_seconds=self.state.operator_absent_seconds,
                max_people=self.state.max_people,
                track_ids=sorted(self.state.track_ids),
            )

    def _close_event(self, now: float) -> None:
        self._close_event_type("machine_stoppage", now)

    def _close_event_type(self, event_type: str, now: float) -> None:
        event_type = "machine_stoppage" if event_type in {"machine_stopped", "machine_stoppage"} else event_type
        event_id = self.state.active_events.get(event_type)
        if not event_id:
            self.state.active_event_since.pop(event_type, None)
            return
        opened_at = self.state.active_event_opened.get(event_type)
        condition_started = self.state.active_event_condition_started.get(event_type)
        duration = max(0.0, now - (condition_started if condition_started is not None else opened_at if opened_at is not None else now))
        with connect() as connection:
            init_db(connection)
            loss = self.estimated_loss(duration)
            if loss is not None:
                merge_event_metadata(connection, event_id, {"estimated_loss": loss, "impact_label": "Impacto operacional estimado"})
            fechar_evento_machine_stoppage(connection, event_id, now_iso(), duration)
        enqueue_event_alert(event_id, phase="normalization")
        self.state.active_events.pop(event_type, None)
        self.state.active_event_since.pop(event_type, None)
        self.state.active_event_opened.pop(event_type, None)
        self.state.active_event_condition_started.pop(event_type, None)
        if event_type == "machine_stoppage":
            self.state.event_id = None
            self.state.event_started_at = None
            self._schedule_replay(event_id)

    def _schedule_replay(self, event_id: str | None = None) -> None:
        event_id = event_id or self.state.event_id
        if not event_id:
            return
        frames = self._event_frames + self.replay_buffer.snapshot(self.config.replay_post_seconds)
        if not frames:
            self._event_frames = []
            return
        config = self.config
        threading.Thread(target=write_replay, args=(event_id, config, frames), daemon=True).start()
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
                    confidence=self.state.confidence,
                    reason=self.state.reason,
                )
                registrar_operational_sample(
                    connection,
                    sample_uuid=new_id("sample"),
                    tenant_id=self.config.client_id,
                    unit_id=self.config.unit_id,
                    camera_id=self.config.camera_id,
                    machine_id=self.config.id,
                    machine_state=self.state.state,
                    operator_present=self.state.operator_present,
                    activity_score=self.state.smoothed_motion,
                    confidence=self.state.confidence,
                    capture_fps=None,
                    inference_fps=None,
                    frames_analyzed=self.state.frames_analyzed,
                    camera_online=True,
                    sample_at=now_iso(),
                    metadata={
                        "changed": changed,
                        "reason": self.state.reason,
                        "people_count": 1 if self.state.operator_present else 0,
                    },
                )
        except Exception:
            pass

    def _calculated_threshold(self) -> float:
        if self.config.active_baseline is not None and self.config.stopped_baseline is not None:
            return calibrate_threshold(self.config.active_baseline, self.config.stopped_baseline)
        return float(self.config.motion_threshold or self.config.motion_sensitivity)

    def _persist_calibration(self, phase: str) -> None:
        status = "active_calibrated" if phase == "active" and self.config.stopped_baseline is None else "calibrated" if self.config.active_baseline is not None and self.config.stopped_baseline is not None else "stopped_calibrated"
        try:
            from app.models import atualizar_machine_monitor
            with connect() as connection:
                init_db(connection)
                atualizar_machine_monitor(
                    connection,
                    self.config.id,
                    motion_threshold=self.config.motion_threshold,
                    calibration_status=status,
                    running_motion=self.config.active_baseline,
                    stopped_motion=self.config.stopped_baseline,
                    active_baseline=self.config.active_baseline,
                    stopped_baseline=self.config.stopped_baseline,
                    active_noise=self.config.active_noise,
                    stopped_noise=self.config.stopped_noise,
                )
        except Exception:
            pass

    def estimated_loss(self, duration_seconds: float) -> float | None:
        minutes = max(0.0, duration_seconds) / 60.0
        if self.config.loss_model == "loss_per_minute" and self.config.loss_per_minute is not None:
            return round(minutes * float(self.config.loss_per_minute), 2)
        if self.config.loss_model == "units_per_minute" and self.config.units_per_minute is not None and self.config.margin_per_unit is not None:
            return round(minutes * float(self.config.units_per_minute) * float(self.config.margin_per_unit), 2)
        return None


def polygon_mask(shape: tuple[int, int], polygon: list[AreaPoint]) -> np.ndarray:
    height, width = shape
    mask = np.zeros((height, width), dtype=np.uint8)
    pts = np.array([[int(point.x * width), int(point.y * height)] for point in polygon], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    return mask


def machine_activity_score(
    frame: np.ndarray,
    polygon: list[AreaPoint] | list[dict[str, float]],
    previous_gray: np.ndarray | None,
) -> tuple[float | None, np.ndarray | None, dict[str, Any]]:
    diagnostics: dict[str, Any] = {
        "analysis_status": "WAITING_FOR_REGION",
        "analysis_error": None,
        "roi_width": 0,
        "roi_height": 0,
    }
    if frame is None or not getattr(frame, "size", 0):
        diagnostics["analysis_status"] = "ERROR"
        diagnostics["analysis_error"] = "Frame inválido."
        return None, previous_gray, diagnostics
    if len(polygon) < 3:
        return None, previous_gray, diagnostics
    points = [
        AreaPoint(float(point["x"]), float(point["y"]))
        for point in normalize_points([{"x": p.x, "y": p.y} if isinstance(p, AreaPoint) else p for p in polygon])
    ]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    pixel_points = np.array([[int(point.x * width), int(point.y * height)] for point in points], dtype=np.int32)
    _x, _y, roi_width, roi_height = cv2.boundingRect(pixel_points)
    diagnostics["roi_width"] = int(roi_width)
    diagnostics["roi_height"] = int(roi_height)
    mask = polygon_mask(gray.shape, points)
    if roi_width <= 1 or roi_height <= 1 or not np.any(mask > 0):
        diagnostics["analysis_status"] = "INVALID_ROI"
        diagnostics["analysis_error"] = "Região da máquina sem área útil."
        return None, previous_gray, diagnostics
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    if previous_gray is None:
        diagnostics["analysis_status"] = "WAITING_FOR_PREVIOUS_FRAME"
        return None, gray, diagnostics
    diff = cv2.absdiff(gray, previous_gray)
    values = diff[mask > 0]
    if not values.size:
        diagnostics["analysis_status"] = "INVALID_ROI"
        diagnostics["analysis_error"] = "Região da máquina não gerou pixels analisáveis."
        return None, gray, diagnostics
    diagnostics["analysis_status"] = "ANALYZING"
    return float(np.mean(values)), gray, diagnostics


def confidence_from_motion(motion: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.5
    return round(min(0.99, max(0.5, 1.0 - (motion / max(threshold, 1e-9)) * 0.5)), 3)


def confidence_from_active_motion(motion: float, threshold: float) -> float:
    if threshold <= 0:
        return 0.5
    return round(min(0.99, max(0.5, (motion / threshold - 1.0) * 0.5 + 0.65)), 3)


def normalized_distance(value: float, target: float, opposite: float) -> float:
    span = max(abs(target - opposite), 1e-9)
    distance = abs(value - opposite) / span
    return round(min(0.99, max(0.5, distance)), 3)


def baseline_stats(values: list[float]) -> tuple[float, float]:
    if not values:
        raise ValueError("Calibracao precisa de ao menos uma amostra de movimento.")
    array = np.array([float(value) for value in values], dtype=float)
    return round(float(np.mean(array)), 3), round(float(np.std(array)), 3)


def merge_event_metadata(connection, event_id: str, values: dict[str, Any]) -> None:
    row = connection.execute("SELECT metadata_json FROM eventos WHERE id = ?", (event_id,)).fetchone()
    metadata: dict[str, Any] = {}
    if row and row["metadata_json"]:
        try:
            metadata = json.loads(row["metadata_json"])
        except Exception:
            metadata = {}
    metadata.update(values)
    connection.execute(
        "UPDATE eventos SET metadata_json = ?, atualizado_em = CURRENT_TIMESTAMP WHERE id = ?",
        (json.dumps(metadata, ensure_ascii=False), event_id),
    )


def save_machine_evidence(frame: np.ndarray, config: MachineMonitorConfig, state: MachineMonitorState) -> tuple[str | None, str | None]:
    try:
        now = datetime.now(timezone.utc).astimezone()
        folder = ROOT / "data" / "evidence" / config.camera_id / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{now:%H%M%S}_{config.id}_machine.jpg"
        annotated = draw_machine_overlay(frame, config, state)
        if not cv2.imwrite(str(path), annotated):
            return None, "Falha ao gravar evidencia da parada."
        relative_path = str(path.relative_to(ROOT))
        try:
            with connect() as connection:
                init_db(connection)
                registrar_evidence_index(
                    connection,
                    evidence_id=new_id("evd"),
                    event_id=state.event_id,
                    event_uuid=None,
                    tenant_id=config.client_id,
                    unit_id=config.unit_id,
                    camera_id=config.camera_id,
                    machine_id=config.id,
                    path=relative_path,
                    media_type="image",
                    size_bytes=path.stat().st_size,
                    metadata={"source": "machine_monitoring"},
                )
        except Exception:
            pass
        return relative_path, None
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
