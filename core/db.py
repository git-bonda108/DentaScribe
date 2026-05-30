"""SQLite persistence layer for consultations."""
import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Any, Optional


DDL = """
CREATE TABLE IF NOT EXISTS consultations (
    id TEXT PRIMARY KEY,
    patient_name TEXT NOT NULL,
    patient_id TEXT,
    doctor_name TEXT,
    chief_complaint TEXT,
    created_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_consultations_patient ON consultations(patient_name);
CREATE INDEX IF NOT EXISTS idx_consultations_created ON consultations(created_at);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    ref_id TEXT,
    before_json TEXT,
    after_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_audit_ref ON audit_log(ref_id);
CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log(ts);
"""


class ConsultationStore:
    def __init__(self, db_path: str = "dentascribe.db"):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as c:
            c.executescript(DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert(self, state: Dict[str, Any]) -> None:
        soap = state.get("soap") or {}
        with self._conn() as c:
            c.execute(
                """INSERT INTO consultations
                   (id, patient_name, patient_id, doctor_name, chief_complaint, created_at, payload_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     patient_name=excluded.patient_name,
                     patient_id=excluded.patient_id,
                     doctor_name=excluded.doctor_name,
                     chief_complaint=excluded.chief_complaint,
                     payload_json=excluded.payload_json""",
                (
                    state["consultation_id"],
                    state.get("patient_name") or "Unknown",
                    state.get("patient_id") or "",
                    state.get("doctor_name") or "",
                    soap.get("chief_complaint") or "",
                    state.get("created_at"),
                    json.dumps(state),
                ),
            )

    def list_all(self, q: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as c:
            if q:
                like = f"%{q}%"
                rows = c.execute(
                    """SELECT * FROM consultations
                       WHERE patient_name LIKE ? OR chief_complaint LIKE ? OR doctor_name LIKE ?
                       ORDER BY created_at DESC LIMIT ?""",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM consultations ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]

    def get(self, consultation_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as c:
            row = c.execute(
                "SELECT payload_json FROM consultations WHERE id = ?",
                (consultation_id,),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def delete(self, consultation_id: str) -> None:
        with self._conn() as c:
            c.execute("DELETE FROM consultations WHERE id = ?", (consultation_id,))

    def count(self) -> int:
        with self._conn() as c:
            return c.execute("SELECT COUNT(*) FROM consultations").fetchone()[0]

    def append_audit(
        self,
        *,
        actor: str,
        action: str,
        ref_id: str = "",
        before: Any = None,
        after: Any = None,
    ) -> None:
        from datetime import datetime
        with self._conn() as c:
            c.execute(
                """INSERT INTO audit_log (ts, actor, action, ref_id, before_json, after_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    datetime.utcnow().isoformat(),
                    actor,
                    action,
                    ref_id or "",
                    json.dumps(before) if before is not None else None,
                    json.dumps(after) if after is not None else None,
                ),
            )

    def list_audit(self, ref_id: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        with self._conn() as c:
            if ref_id:
                rows = c.execute(
                    """SELECT ts, actor, action, ref_id FROM audit_log
                       WHERE ref_id = ? ORDER BY ts DESC LIMIT ?""",
                    (ref_id, limit),
                ).fetchall()
            else:
                rows = c.execute(
                    """SELECT ts, actor, action, ref_id FROM audit_log
                       ORDER BY ts DESC LIMIT ?""",
                    (limit,),
                ).fetchall()
        return [dict(r) for r in rows]
