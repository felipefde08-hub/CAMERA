from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from visual_ops_mvp.database import connect, init_db
from visual_ops_mvp.reports import daily_report
from visual_ops_mvp.repository import (
    add_alert,
    add_camera,
    add_event,
    add_rule,
    add_site,
    add_tenant,
)


class MvpDatabaseTest(unittest.TestCase):
    def test_registers_core_entities_and_daily_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.sqlite3"
            with connect(db_path) as connection:
                init_db(connection)
                tenant_id = add_tenant(connection, "Cliente Teste")
                site_id = add_site(connection, tenant_id, "Unidade 1")
                camera_id = add_camera(connection, tenant_id, site_id, "Camera Entrada")
                rule_id = add_rule(
                    connection,
                    tenant_id,
                    site_id,
                    "Parada de maquina",
                    "machine_stopped",
                    camera_id,
                )
                event_id = add_event(
                    connection,
                    tenant_id,
                    site_id,
                    camera_id,
                    rule_id,
                    "machine_stopped",
                    "2026-07-15T10:00:00-03:00",
                    "2026-07-15T10:05:00-03:00",
                    300.0,
                    "warning",
                )
                add_alert(
                    connection,
                    tenant_id,
                    site_id,
                    camera_id,
                    rule_id,
                    "Maquina parada",
                    "Parada detectada por mais de 5 minutos.",
                    event_id,
                )

                report = daily_report(connection, "2026-07-15")

        self.assertIn("Cliente Teste", report)
        self.assertIn("Unidade 1", report)
        self.assertIn("Camera Entrada", report)
        self.assertIn("5.0 min", report)


if __name__ == "__main__":
    unittest.main()

