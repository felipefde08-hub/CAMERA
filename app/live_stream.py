from __future__ import annotations

import threading
import time
from dataclasses import asdict, dataclass
from typing import Callable

import cv2

from app.database import connect, init_db
from edge_agent.camera_connector import CameraSource, UniversalCameraConnector, now_iso
from app.person_detection import Detection, PersonAnalysisEngine
from app.incidents import IncidentManager
from app.machine_monitoring import MachineMonitorEngine, config_from_dict, draw_machine_overlay
from app.models import listar_areas_ativas_camera, listar_machine_monitors_ativos_camera
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

    def to_public_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["ids_na_area"] = self.ids_na_area or []
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
        self._area_presence_tracker = AreaPresenceTracker()
        self._active_area: RestrictedArea | None = None
        self._last_area_load_seconds = 0.0
        self._incident_manager = IncidentManager(camera_id)
        self._machine_engines: dict[str, MachineMonitorEngine] = {}
        self._last_machine_load_seconds = 0.0

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
        with self._lock:
            self.status.status = "offline"
            self.status.viewers = 0
            self.status.ai_status = "inativa"

    def set_analysis(self, enabled: bool) -> dict[str, object]:
        with self._lock:
            self._analysis_enabled = enabled
            if not enabled:
                self._last_detections = []
                self.status.ai_status = "inativa"
                self.status.people_count = 0
                self.status.analysis_error = None
                return self.status.to_public_dict()
            self.status.ai_status = "carregando"
        return self.public_status()

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

    def _load_active_area(self) -> RestrictedArea | None:
        now = time.monotonic()
        if now - self._last_area_load_seconds < 2.0:
            return self._active_area
        self._last_area_load_seconds = now
        try:
            with connect() as connection:
                init_db(connection)
                areas = listar_areas_ativas_camera(connection, self.camera_id)
            self._active_area = area_from_dict(areas[0]) if areas else None
        except Exception:
            self._active_area = None
        return self._active_area

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
        area = self._load_active_area()
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
            output = draw_area_overlay(frame, area, presence, set(), [])
            return self._update_machines(output, self._load_machine_engines())
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
                    self.status.people_count = len(detections)
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
        if area is not None:
            output = draw_area_overlay(frame, area, presence, inside_ids, self._last_detections)
            incident_state = self._incident_manager.update(area, presence, self._last_detections, output)
            output = self._update_machines(output, machine_engines)
            with self._lock:
                for key, value in incident_state.items():
                    setattr(self.status, key, value)
            return output
        self._incident_manager.update(None, presence, self._last_detections, frame)
        output = engine.draw(frame, self._last_detections)
        return self._update_machines(output, machine_engines)

    def _update_machines(self, frame, machine_engines: list[MachineMonitorEngine]):
        output = frame
        for engine in machine_engines:
            try:
                state = engine.update(output, self._last_detections)
                output = draw_machine_overlay(output, engine.config, state)
                with self._lock:
                    self.status.machine_state = state.state
                    self.status.machine_motion = round(state.smoothed_motion, 3)
                    self.status.machine_threshold = round(state.threshold, 3)
                    self.status.machine_operator_present = state.operator_present
                    self.status.machine_event_id = state.event_id
            except Exception as exc:
                with self._lock:
                    self.status.machine_state = "unavailable"
                    self.status.analysis_error = str(exc)
        return output

    def _run(self) -> None:
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
                        break

                    output_frame = self._maybe_analyze(frame)
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
            connector.stop()
            self._incident_manager.close_interrupted()
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
            return self.status.to_public_dict()


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
