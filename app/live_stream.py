from __future__ import annotations

import threading
import time
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

import cv2
import numpy as np

from app.database import connect, init_db
from edge_agent.camera_connector import CameraSource, UniversalCameraConnector, now_iso
from app.live_view_ops import LiveViewOpsEngine
from app.person_detection import Detection, PersonAnalysisEngine
from app.incidents import IncidentManager
from app.people_zones import PeopleZonesEngine
from app.machine_monitoring import MachineMonitorEngine, config_from_dict, draw_machine_overlay
from app.models import atualizar_machine_monitor, listar_areas_ativas_camera, listar_machine_monitors_ativos_camera, registrar_machine_calibration
from app.operations_history import OperationsRecorder
from app.observation_engine import ObservationEngine
from app.operational_rule_runtime import OperationalRuleRuntime, facts_from_stream
from app.restricted_area import (
    AreaPresence,
    AreaPresenceTracker,
    RestrictedArea,
    area_from_dict,
    draw_area_overlay,
    evaluate_area,
)


@dataclass
class LiveStreamStatus:
    camera_id: str
    status: str = "offline"
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    last_frame_at: str | None = None
    error: str | None = None
    viewers: int = 0
    reconnect_attempts: int = 0
    ai_status: str = "inativa"
    ai_model: str | None = None
    analysis_fps: float | None = None
    people_count: int = 0
    last_analysis_at: str | None = None
    analysis_error: str | None = None
    area_id: str | None = None
    area_nome: str | None = None
    area_estado: str = "livre"
    pessoas_na_area: int = 0
    ids_na_area: list[int] | None = None
    incident_active: bool = False
    incident_id: str | None = None
    incident_started_at: str | None = None
    incident_duration: float | None = None
    incident_people: int = 0
    machine_state: str = "unavailable"
    machine_motion: float | None = None
    machine_threshold: float | None = None
    machine_operator_present: bool = False
    machine_event_id: str | None = None
    zones: list[dict[str, object]] | None = None
    active_zone_events: list[dict[str, object]] | None = None
    observation: dict[str, object] | None = None
    calibration: dict[str, object] | None = None

    def to_public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ids_na_area"] = self.ids_na_area or []
        data["zones"] = self.zones or []
        data["active_zone_events"] = self.active_zone_events or []
        data["observation"] = self.observation or {}
        data["calibration"] = self.calibration or {}
        return data


class LiveCameraStream:
    def __init__(
        self,
        camera_id: str,
        source: str,
        connector_factory: Callable[[CameraSource], UniversalCameraConnector] | None = None,
    ) -> None:
        self.camera_id = camera_id
        self.source = source
        self.connector_factory = connector_factory or (lambda camera: UniversalCameraConnector(camera))
        self.status = LiveStreamStatus(camera_id=camera_id, status="offline")
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_jpeg: bytes | None = None
        self._analysis_enabled = False
        self._analysis_engine: PersonAnalysisEngine | None = None
        self._last_detections: list[Detection] = []
        self._last_analysis_seconds = 0.0
        self._analysis_frames = 0
        self._analysis_started = time.monotonic()
        self._analysis_worker_stop = threading.Event()
        self._analysis_worker_thread: threading.Thread | None = None
        self._analysis_frame_lock = threading.Lock()
        self._analysis_frame = None
        self._last_raw_frame = None
        self._area_presence_tracker = AreaPresenceTracker()
        self._active_area: RestrictedArea | None = None
        self._active_areas: list[dict[str, object]] = []
        self._last_area_load_seconds = 0.0
        self._incident_manager = IncidentManager(camera_id)
        self._people_zones = PeopleZonesEngine(camera_id)
        self._machine_engines: dict[str, MachineMonitorEngine] = {}
        self._last_machine_load_seconds = 0.0
        self.live_view_ops: LiveViewOpsEngine | None = None
        self._operations_recorder = OperationsRecorder(camera_id, camera_id)
        self._rule_runtime = OperationalRuleRuntime(camera_id)
        self._observation_engine = ObservationEngine(camera_id)
        self._calibration_lock = threading.Lock()
        self._calibration: dict[str, Any] | None = None

    def _evaluate_rules(
        self,
        frame=None,
        area_presence: AreaPresence | None = None,
        machine_state: str | None = None,
        machine_motion: float | None = None,
        operator_present: bool | None = None,
        operator_people_count: int | None = None,
        confidence: float | None = None,
        force: bool = False,
    ) -> None:
        with self._lock:
            status = self.status.status
            fps = self.status.fps
            detections = list(self._last_detections)
        facts = facts_from_stream(
            self.camera_id,
            status,
            detections=detections,
            area_presence=area_presence,
            machine_state=machine_state,
            machine_motion=machine_motion,
            operator_present=operator_present,
            operator_people_count=operator_people_count,
            fps=fps,
            confidence=confidence,
        )
        self._rule_runtime.evaluate(facts, frame=frame, force=force)

    def enable_live_view_ops(self) -> LiveViewOpsEngine:
        with self._lock:
            if self.live_view_ops is None:
                self.live_view_ops = LiveViewOpsEngine()
            return self.live_view_ops

    def start(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop_event.clear()
            self.status.status = "conectando"
            self._thread = threading.Thread(target=self._run, name=f"live-{self.camera_id}", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        thread = self._thread
        if thread:
            thread.join(timeout=5.0)
        self._incident_manager.close_interrupted()
        self._people_zones.close_interrupted()
        self._rule_runtime.camera_status("offline", self._last_raw_frame)
        with self._lock:
            self.status.status = "offline"
            self.status.viewers = 0
            self.status.ai_status = "inativa"

    def set_analysis(self, enabled: bool) -> dict[str, object]:
        with self._lock:
            self._analysis_enabled = enabled
            live_ops = self.live_view_ops
            if not enabled:
                self._analysis_worker_stop.set()
                self._last_detections = []
                self.status.ai_status = "inativa"
                self.status.people_count = 0
                self.status.analysis_error = None
                if live_ops:
                    live_ops.set_ai(False)
                return self.status.to_public_dict()
            self.status.ai_status = "carregando"
            if live_ops:
                live_ops.set_ai(True)
                self._ensure_analysis_worker()
        return self.public_status()

    def _ensure_analysis_worker(self) -> None:
        if self._analysis_worker_thread and self._analysis_worker_thread.is_alive():
            return
        self._analysis_worker_stop.clear()
        self._analysis_worker_thread = threading.Thread(
            target=self._analysis_worker,
            name=f"analysis-{self.camera_id}",
            daemon=True,
        )
        self._analysis_worker_thread.start()

    def _analysis_worker(self) -> None:
        while not self._analysis_worker_stop.is_set():
            engine = self._ensure_analysis_engine()
            if engine is None:
                self._analysis_worker_stop.wait(1.0)
                continue
            with self._analysis_frame_lock:
                frame = self._analysis_frame.copy() if self._analysis_frame is not None else None
                self._analysis_frame = None
            if frame is None:
                self._analysis_worker_stop.wait(0.05)
                continue
            try:
                detections = engine.analyze(frame)
                now = time.monotonic()
                self._analysis_frames += 1
                elapsed = max(0.001, now - self._analysis_started)
                with self._lock:
                    self._last_detections = detections
                    self.status.ai_status = "ativa"
                    self.status.ai_model = engine.model_name
                    self.status.analysis_fps = round(self._analysis_frames / elapsed, 2)
                    self.status.people_count = len([d for d in detections if d.class_name == "person"])
                    self.status.last_analysis_at = now_iso()
                    self.status.analysis_error = None
            except Exception as exc:
                with self._lock:
                    self.status.ai_status = "indisponivel"
                    self.status.analysis_error = str(exc)

    def _submit_analysis_frame(self, frame, analysis_fps: float) -> None:
        now = time.monotonic()
        interval = 1.0 / max(0.1, analysis_fps)
        if now - self._last_analysis_seconds < interval:
            return
        self._last_analysis_seconds = now
        with self._analysis_frame_lock:
            self._analysis_frame = frame.copy()

    def _ensure_analysis_engine(self) -> PersonAnalysisEngine | None:
        if self._analysis_engine is not None:
            return self._analysis_engine
        try:
            self._analysis_engine = PersonAnalysisEngine()
            with self._lock:
                self.status.ai_model = self._analysis_engine.model_name
                self.status.ai_status = "ativa"
                self.status.analysis_error = None
            return self._analysis_engine
        except Exception as exc:
            with self._lock:
                self.status.ai_status = "indisponivel"
                self.status.analysis_error = str(exc)
            return None

    def start_machine_calibration(self, monitor: dict[str, Any], region: list[dict[str, float]], phase: str, duration_seconds: float = 30.0) -> dict[str, object]:
        if phase not in {"active", "stopped"}:
            raise ValueError("Fase de calibracao invalida.")
        with self._calibration_lock:
            if self._calibration and self._calibration.get("status") == "running":
                raise RuntimeError("Ja existe uma calibracao em andamento nesta camera.")
            started = now_iso()
            self._calibration = {
                "status": "running",
                "phase": phase,
                "machine_id": monitor["id"],
                "camera_id": self.camera_id,
                "duration_seconds": max(0.01, float(duration_seconds)),
                "started_at": started,
                "started_monotonic": time.monotonic(),
                "samples": [],
                "invalid_frames": 0,
                "region": region,
                "previous_gray": None,
                "algorithm_version": "frame-diff-roi-v1",
                "result": None,
                "error": None,
            }
        return self.calibration_status()

    def calibration_status(self) -> dict[str, object]:
        with self._calibration_lock:
            if not self._calibration:
                return {"status": "idle"}
            data = {key: value for key, value in self._calibration.items() if key not in {"previous_gray", "samples"}}
            samples = list(self._calibration.get("samples") or [])
        elapsed = max(0.0, time.monotonic() - float(data.get("started_monotonic") or time.monotonic()))
        duration = float(data.get("duration_seconds") or 1.0)
        data["progress"] = min(100, round((elapsed / duration) * 100, 1)) if data.get("status") == "running" else 100
        data["samples_count"] = len(samples)
        data["last_sample"] = samples[-1] if samples else None
        data.pop("started_monotonic", None)
        return data

    def _update_calibration(self, frame) -> None:
        with self._calibration_lock:
            session = self._calibration
            if not session or session.get("status") != "running":
                return
            elapsed = time.monotonic() - float(session["started_monotonic"])
            duration = float(session["duration_seconds"])
            if elapsed >= duration:
                session["status"] = "finishing"
                snapshot = dict(session)
            else:
                snapshot = None
                try:
                    score, previous = calibration_activity_score(frame, session["region"], session.get("previous_gray"))
                    session["previous_gray"] = previous
                    if score is None:
                        session["invalid_frames"] += 1
                    else:
                        session["samples"].append(round(float(score), 4))
                except Exception as exc:
                    session["invalid_frames"] += 1
                    session["error"] = str(exc)
                return
        self._finish_calibration(snapshot)

    def _finish_calibration(self, session: dict[str, Any]) -> None:
        samples = list(session.get("samples") or [])
        finished = now_iso()
        if not samples:
            result = {
                "status": "failed",
                "phase": session["phase"],
                "error": "Nenhuma amostra valida foi capturada.",
                "samples_count": 0,
                "finished_at": finished,
            }
            with self._calibration_lock:
                self._calibration = {**session, **result}
            return
        stats = calibration_stats(samples)
        phase = str(session["phase"])
        monitor_id = str(session["machine_id"])
        algorithm = str(session["algorithm_version"])
        region = list(session.get("region") or [])
        try:
            with connect() as connection:
                init_db(connection)
                registrar_machine_calibration(
                    connection,
                    machine_id=monitor_id,
                    camera_id=self.camera_id,
                    phase=phase,
                    samples=samples,
                    stats=stats,
                    algorithm_version=algorithm,
                    region=region,
                    started_at=str(session["started_at"]),
                    finished_at=finished,
                )
                monitor = next((item for item in listar_machine_monitors_ativos_camera(connection, self.camera_id) if item["id"] == monitor_id), None)
                active_calibration = stats if phase == "active" else (monitor or {}).get("active_calibration")
                stopped_calibration = stats if phase == "stopped" else (monitor or {}).get("stopped_calibration")
                separation = calibration_separation(active_calibration, stopped_calibration)
                atualizar_machine_monitor(
                    connection,
                    monitor_id,
                    motion_threshold=separation.get("threshold"),
                    calibration_status="calibrated" if separation["result"] == "READY" else "calibration_needs_review",
                    running_motion=active_calibration.get("mean") if active_calibration else None,
                    stopped_motion=stopped_calibration.get("mean") if stopped_calibration else None,
                    active_baseline=active_calibration.get("mean") if active_calibration else None,
                    stopped_baseline=stopped_calibration.get("mean") if stopped_calibration else None,
                    active_noise=active_calibration.get("std") if active_calibration else None,
                    stopped_noise=stopped_calibration.get("std") if stopped_calibration else None,
                    active_calibration=active_calibration if phase == "active" else None,
                    stopped_calibration=stopped_calibration if phase == "stopped" else None,
                    separation_score=separation.get("score"),
                    calibration_result=separation["result"],
                    calibration_algorithm_version=algorithm,
                )
        except Exception as exc:
            with self._calibration_lock:
                self._calibration = {**session, "status": "failed", "error": str(exc), "samples_count": len(samples), "finished_at": finished}
            return
        with self._calibration_lock:
            self._calibration = {
                "status": "completed",
                "phase": phase,
                "machine_id": monitor_id,
                "camera_id": self.camera_id,
                "samples_count": len(samples),
                "invalid_frames": int(session.get("invalid_frames") or 0),
                "stats": stats,
                "separation": separation,
                "started_at": session["started_at"],
                "finished_at": finished,
                "algorithm_version": algorithm,
            }
        with self._lock:
            self.status.calibration = self.calibration_status()

    def _load_active_areas(self) -> list[dict[str, object]]:
        now = time.monotonic()
        if now - self._last_area_load_seconds < 2.0:
            return self._active_areas
        self._last_area_load_seconds = now
        try:
            with connect() as connection:
                init_db(connection)
                areas = listar_areas_ativas_camera(connection, self.camera_id)
            self._active_areas = areas
            self._active_area = area_from_dict(areas[0]) if areas else None
        except Exception:
            self._active_areas = []
            self._active_area = None
        return self._active_areas

    def _load_machine_engines(self) -> list[MachineMonitorEngine]:
        now = time.monotonic()
        if now - self._last_machine_load_seconds < 2.0:
            return list(self._machine_engines.values())
        self._last_machine_load_seconds = now
        try:
            with connect() as connection:
                init_db(connection)
                monitors = listar_machine_monitors_ativos_camera(connection, self.camera_id)
            active_ids = {monitor["id"] for monitor in monitors}
            for stale_id in set(self._machine_engines) - active_ids:
                self._machine_engines.pop(stale_id, None)
            for monitor in monitors:
                if monitor["id"] not in self._machine_engines:
                    self._machine_engines[monitor["id"]] = MachineMonitorEngine(config_from_dict(monitor))
        except Exception:
            return list(self._machine_engines.values())
        return list(self._machine_engines.values())

    def _maybe_analyze(self, frame):
        with self._lock:
            enabled = self._analysis_enabled
        areas = self._load_active_areas()
        area = area_from_dict(areas[0]) if areas else None
        if not enabled:
            presence = AreaPresence(
                area_id=area.id if area else None,
                area_nome=area.nome if area else None,
            )
            with self._lock:
                self.status.area_id = presence.area_id
                self.status.area_nome = presence.area_nome
                self.status.area_estado = presence.estado
                self.status.pessoas_na_area = presence.pessoas_dentro
                self.status.ids_na_area = presence.ids_dentro or []
                self.status.zones = []
                self.status.active_zone_events = []
            output = draw_area_overlay(frame, area, presence, set(), [])
            output = self._update_machines(output, self._load_machine_engines(), presence)
            self._evaluate_rules(output, area_presence=presence)
            return output
        engine = self._ensure_analysis_engine()
        if engine is None:
            return frame
        now = time.monotonic()
        interval = 1.0 / max(0.1, engine.analysis_fps)
        if now - self._last_analysis_seconds >= interval:
            try:
                detections = engine.analyze(frame)
                self._last_detections = detections
                self._last_analysis_seconds = now
                self._analysis_frames += 1
                elapsed = max(0.001, now - self._analysis_started)
                with self._lock:
                    self.status.ai_status = "ativa"
                    self.status.ai_model = engine.model_name
                    self.status.analysis_fps = round(self._analysis_frames / elapsed, 2)
                    self.status.people_count = len([d for d in detections if d.class_name == "person"])
                    self.status.last_analysis_at = now_iso()
                    self.status.analysis_error = None
            except Exception as exc:
                with self._lock:
                    self.status.ai_status = "indisponivel"
                    self.status.analysis_error = str(exc)
                return frame
        height, width = frame.shape[:2]
        presence, inside_ids = evaluate_area(area, self._last_detections, width, height, self._area_presence_tracker)
        with self._lock:
            self.status.area_id = presence.area_id
            self.status.area_nome = presence.area_nome
            self.status.area_estado = presence.estado
            self.status.pessoas_na_area = presence.pessoas_dentro
            self.status.ids_na_area = presence.ids_dentro or []
        machine_engines = self._load_machine_engines()
        if areas:
            output, people_zones = self._people_zones.update(areas, self._last_detections, frame)
            output = self._update_machines(output, machine_engines, presence, people_zones.get("zones") or [])
            with self._lock:
                self.status.zones = people_zones.get("zones") or []
                self.status.active_zone_events = people_zones.get("active_events") or []
                first_active = (people_zones.get("active_events") or [None])[0]
                self.status.incident_active = bool(first_active)
                self.status.incident_id = first_active.get("event_id") if first_active else None
                self.status.incident_started_at = first_active.get("started_at_iso") if first_active else None
                self.status.incident_people = int(first_active.get("current_people") or 0) if first_active else 0
            self._evaluate_rules(output, area_presence=presence)
            return output
        self._people_zones.update([], self._last_detections, frame)
        output = engine.draw(frame, self._last_detections)
        output = self._update_machines(output, machine_engines, presence)
        self._evaluate_rules(output, area_presence=presence)
        return output

    def _maybe_live_view_ops(self, frame):
        with self._lock:
            live_ops = self.live_view_ops
        if live_ops is None:
            return self._maybe_analyze(frame)
        if live_ops.state.ai_enabled:
            self._ensure_analysis_worker()
            engine = self._analysis_engine
            analysis_fps = engine.analysis_fps if engine else float(os.getenv("CAMPEX_ANALYSIS_FPS", "2"))
            self._submit_analysis_frame(frame, analysis_fps)
        output = live_ops.update(frame, self._last_detections if live_ops.state.ai_enabled else [])
        self._operations_recorder.update_status(self.status.status, live_ops.public_state(), output)
        ops = live_ops.public_state()
        self._evaluate_rules(
            output,
            machine_state=ops.get("machine_state"),
            machine_motion=ops.get("machine_motion"),
            operator_present=bool(ops.get("operator_present")),
            operator_people_count=int(ops.get("operator_people_count") or 0),
            confidence=ops.get("visual_confidence"),
        )
        return output

    def _update_machines(self, frame, machine_engines: list[MachineMonitorEngine], area_presence: AreaPresence | None = None, zone_states: list[dict[str, object]] | None = None):
        output = frame
        zone_states = list(zone_states or [])
        for engine in machine_engines:
            try:
                state = engine.update(output, self._last_detections)
                output = draw_machine_overlay(output, engine.config, state)
                machine_state = "ACTIVE" if state.state == "ACTIVE" else "STOPPED" if state.state == "STOPPED" else "UNKNOWN"
                if area_presence and not zone_states:
                    zone_states.append({**area_presence.to_dict(), "tipo": "restricted_zone"})
                observation = self._observation_engine.build(
                    machine_id=engine.config.id,
                    machine_state=machine_state,
                    machine_activity_score=state.smoothed_motion,
                    machine_confidence=state.confidence,
                    operator_present=state.operator_present,
                    zone_states=zone_states or [],
                )
                with self._lock:
                    self.status.machine_state = state.state
                    self.status.machine_motion = round(state.smoothed_motion, 3)
                    self.status.machine_threshold = round(state.threshold, 3)
                    self.status.machine_operator_present = state.operator_present
                    self.status.machine_event_id = state.event_id
                    self.status.observation = observation
                self._evaluate_rules(
                    output,
                    area_presence=area_presence,
                    machine_state="ATIVA" if state.state == "ACTIVE" else "PARADA" if state.state == "STOPPED" else "UNKNOWN",
                    machine_motion=state.smoothed_motion,
                    operator_present=state.operator_present,
                    operator_people_count=1 if state.operator_present else 0,
                    confidence=state.confidence,
                )
            except Exception as exc:
                with self._lock:
                    self.status.machine_state = "unavailable"
                    self.status.analysis_error = str(exc)
        return output

    def _run(self) -> None:
        self._analysis_worker_stop.clear()
        reconnect_delay = 1.0
        connector = self.connector_factory(
            CameraSource(camera_id=self.camera_id, source=self.source, reconnect_seconds=1.0)
        )
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    self.status.status = "conectando" if self.status.reconnect_attempts == 0 else "reconectando"
                if not connector.open():
                    with self._lock:
                        self.status.status = "reconectando"
                        self.status.error = connector.info.error
                    self.status.reconnect_attempts += 1
                    self._operations_recorder.update_status("offline", self.live_view_ops.public_state() if self.live_view_ops else None)
                    self._rule_runtime.camera_status("offline", self._last_raw_frame)
                    self._stop_event.wait(reconnect_delay)
                    reconnect_delay = min(10.0, reconnect_delay * 1.5)
                    continue

                reconnect_delay = 1.0
                with self._lock:
                    self.status.status = "online"
                    self.status.error = None
                    self.status.width = connector.info.width
                    self.status.height = connector.info.height
                    self.status.fps = connector.info.fps
                self._operations_recorder.update_status("online", self.live_view_ops.public_state() if self.live_view_ops else None)
                self._rule_runtime.camera_status("online")

                frame_count = 0
                fps_started = time.monotonic()
                while not self._stop_event.is_set():
                    ok, frame = connector.capture.read() if connector.capture else (False, None)
                    if not ok or frame is None:
                        connector.close()
                        with self._lock:
                            self.status.status = "reconectando"
                            self.status.error = "Stream parou de entregar frames."
                            self.status.reconnect_attempts += 1
                        self._operations_recorder.update_status("offline", self.live_view_ops.public_state() if self.live_view_ops else None)
                        self._rule_runtime.camera_status("offline", self._last_raw_frame)
                        break

                    self._last_raw_frame = frame.copy()
                    self._update_calibration(frame)
                    output_frame = self._maybe_live_view_ops(frame)
                    encoded, jpeg = cv2.imencode(".jpg", output_frame)
                    if not encoded:
                        continue
                    frame_count += 1
                    elapsed = max(0.001, time.monotonic() - fps_started)
                    height, width = frame.shape[:2]
                    with self._lock:
                        self._last_jpeg = jpeg.tobytes()
                        self.status.status = "online"
                        self.status.width = width
                        self.status.height = height
                        self.status.fps = round(frame_count / elapsed, 2)
                        self.status.last_frame_at = now_iso()
                        self.status.error = None
        finally:
            self._analysis_worker_stop.set()
            analysis_thread = self._analysis_worker_thread
            if analysis_thread:
                analysis_thread.join(timeout=3.0)
            connector.stop()
            self._incident_manager.close_interrupted()
            self._people_zones.close_interrupted()
            with self._lock:
                if self.status.status != "offline":
                    self.status.status = "offline"

    def frames(self):
        self.start()
        with self._lock:
            self.status.viewers += 1
        try:
            while not self._stop_event.is_set():
                with self._lock:
                    jpeg = self._last_jpeg
                    status = self.status.status
                if jpeg is None:
                    if status in {"offline", "erro"}:
                        break
                    time.sleep(0.2)
                    continue
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
                time.sleep(0.03)
        finally:
            with self._lock:
                self.status.viewers = max(0, self.status.viewers - 1)

    def public_status(self) -> dict[str, object]:
        with self._lock:
            data = self.status.to_public_dict()
            if data.get("status") in {"conectando", "reconectando"} and self._last_jpeg is not None:
                last_frame_at = str(data.get("last_frame_at") or "")
                try:
                    parsed = datetime.fromisoformat(last_frame_at.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    is_recent = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds() <= 5
                except ValueError:
                    is_recent = False
                if is_recent:
                    data["status"] = "online"
                    data["error"] = None
            data["calibration"] = self.calibration_status()
            return data


def calibration_activity_score(frame, polygon: list[dict[str, float]], previous_gray):
    if frame is None or not polygon or len(polygon) < 3:
        return None, previous_gray
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)
    mask = np.zeros(gray.shape, dtype=np.uint8)
    height, width = gray.shape[:2]
    pts = np.array([[int(max(0, min(1, float(point["x"]))) * width), int(max(0, min(1, float(point["y"]))) * height)] for point in polygon], dtype=np.int32)
    cv2.fillPoly(mask, [pts], 255)
    if previous_gray is None:
        return None, gray
    diff = cv2.absdiff(gray, previous_gray)
    values = diff[mask > 0]
    if values.size == 0:
        return None, gray
    return float(np.mean(values)), gray


def calibration_stats(samples: list[float]) -> dict[str, object]:
    array = np.array(samples, dtype=float)
    return {
        "samples_count": int(array.size),
        "mean": round(float(np.mean(array)), 4),
        "median": round(float(np.median(array)), 4),
        "std": round(float(np.std(array)), 4),
        "min": round(float(np.min(array)), 4),
        "max": round(float(np.max(array)), 4),
        "p10": round(float(np.percentile(array, 10)), 4),
        "p25": round(float(np.percentile(array, 25)), 4),
        "p75": round(float(np.percentile(array, 75)), 4),
        "p90": round(float(np.percentile(array, 90)), 4),
        "p95": round(float(np.percentile(array, 95)), 4),
    }


def calibration_separation(active: dict[str, object] | None, stopped: dict[str, object] | None) -> dict[str, object]:
    if not active or not stopped:
        return {"result": "INVALID", "score": None, "overlap": None, "threshold": None, "message": "Calibre ativa e parada para calcular separacao."}
    active_mean = float(active.get("mean") or 0)
    stopped_mean = float(stopped.get("mean") or 0)
    active_std = float(active.get("std") or 0)
    stopped_std = float(stopped.get("std") or 0)
    distance = active_mean - stopped_mean
    noise = max(active_std + stopped_std, 1e-6)
    score = round(distance / noise, 3)
    overlap = not (float(stopped.get("p90") or stopped_mean) < float(active.get("p10") or active_mean))
    threshold = round((active_mean + stopped_mean) / 2.0, 4)
    if distance <= 0:
        result = "INVALID"
        message = "A atividade parada ficou igual ou maior que a ativa. Reposicione a ROI."
    elif score >= 3 and not overlap:
        result = "READY"
        message = "Ativa e parada visualmente distinguiveis."
    elif score >= 1.5:
        result = "WEAK_SEPARATION"
        message = "Separacao fraca. Reposicione a ROI ou valide tecnicamente antes de monitorar."
    else:
        result = "INVALID"
        message = "Separacao insuficiente entre ativa e parada."
    return {"result": result, "score": score, "overlap": overlap, "threshold": threshold, "message": message}


class LiveStreamManager:
    def __init__(
        self,
        connector_factory: Callable[[CameraSource], UniversalCameraConnector] | None = None,
    ) -> None:
        self.connector_factory = connector_factory
        self._lock = threading.Lock()
        self._streams: dict[str, LiveCameraStream] = {}

    def get_or_create(self, camera_id: str, source: str) -> LiveCameraStream:
        with self._lock:
            stream = self._streams.get(camera_id)
            if stream is None:
                stream = LiveCameraStream(camera_id, source, self.connector_factory)
                self._streams[camera_id] = stream
            return stream

    def get(self, camera_id: str) -> LiveCameraStream | None:
        with self._lock:
            return self._streams.get(camera_id)

    def statuses(self) -> list[dict[str, object]]:
        with self._lock:
            streams = list(self._streams.values())
        return [stream.public_status() for stream in streams]

    def stop(self, camera_id: str) -> bool:
        with self._lock:
            stream = self._streams.pop(camera_id, None)
        if stream is None:
            return False
        stream.stop()
        return True

    def stop_all(self) -> None:
        with self._lock:
            streams = list(self._streams.values())
            self._streams.clear()
        for stream in streams:
            stream.stop()
