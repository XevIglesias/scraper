import sqlite3
import json
import threading
from datetime import datetime


class ReplicatorDB:
    def __init__(self, db_path="replicator.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._inicializar_db()

    def _inicializar_db(self):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                # Tablas originales
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reputacion_tiendas (
                        dominio TEXT PRIMARY KEY,
                        veces_reacondicionado INTEGER DEFAULT 0,
                        veces_nuevo INTEGER DEFAULT 0,
                        ultima_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS memoria_errores (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        dominio TEXT,
                        url TEXT,
                        tipo_error TEXT,
                        leccion TEXT,
                        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                # Tabla de generaciones del bucle evolutivo
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS generations (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP,
                        phase       TEXT,
                        target_file TEXT,
                        func_name   TEXT,
                        fitness_before REAL,
                        fitness_after  REAL,
                        delta_pct      REAL,
                        snapshot_id    TEXT,
                        approved    INTEGER DEFAULT 0,
                        notes       TEXT
                    )
                ''')
                # Historial de métricas por generación
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS metrics_history (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        timestamp     DATETIME DEFAULT CURRENT_TIMESTAMP,
                        metric_name   TEXT,
                        value         REAL,
                        generation_id INTEGER REFERENCES generations(id)
                    )
                ''')
                conn.commit()

    # ── API original ──────────────────────────────────────────────────────────

    def registrar_error(self, dominio: str, url: str, tipo: str, leccion: str):
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT INTO memoria_errores (dominio, url, tipo_error, leccion) VALUES (?,?,?,?)',
                    (dominio, url, tipo, leccion)
                )
                conn.commit()

    def obtener_lecciones(self, dominio: str) -> list[str]:
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                rows = conn.execute(
                    'SELECT leccion FROM memoria_errores WHERE dominio = ?', (dominio,)
                ).fetchall()
                return [r[0] for r in rows]

    # ── API del bucle evolutivo ───────────────────────────────────────────────

    def store_generation(
        self,
        phase: str,
        target_file: str,
        func_name: str,
        fitness_before: float = 0.0,
        fitness_after: float = 0.0,
        delta_pct: float = 0.0,
        snapshot_id: str = "",
        approved: bool = False,
        notes: str = "",
    ) -> int:
        """Registra un ciclo de evolución. Devuelve el ID de la generación."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cur = conn.execute(
                    '''INSERT INTO generations
                       (phase, target_file, func_name, fitness_before, fitness_after,
                        delta_pct, snapshot_id, approved, notes)
                       VALUES (?,?,?,?,?,?,?,?,?)''',
                    (phase, target_file, func_name, fitness_before, fitness_after,
                     delta_pct, snapshot_id, 1 if approved else 0, notes)
                )
                conn.commit()
                return cur.lastrowid

    def update_generation_phase(self, gen_id: int, phase: str, approved: bool = False, notes: str = ""):
        """Actualiza la fase de una generación existente (ej: proposed → approved)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'UPDATE generations SET phase=?, approved=?, notes=? WHERE id=?',
                    (phase, 1 if approved else 0, notes, gen_id)
                )
                conn.commit()

    def store_metric(self, metric_name: str, value: float, generation_id: int):
        """Guarda una métrica individual asociada a una generación."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    'INSERT INTO metrics_history (metric_name, value, generation_id) VALUES (?,?,?)',
                    (metric_name, value, generation_id)
                )
                conn.commit()

    def get_generation_history(self, limit: int = 20) -> list[dict]:
        """Devuelve las últimas N generaciones del bucle evolutivo."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    'SELECT * FROM generations ORDER BY id DESC LIMIT ?', (limit,)
                ).fetchall()
                return [dict(r) for r in rows]

    def get_metrics_for_generation(self, generation_id: int) -> list[dict]:
        """Devuelve todas las métricas de una generación específica."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    'SELECT metric_name, value, timestamp FROM metrics_history WHERE generation_id=?',
                    (generation_id,)
                ).fetchall()
                return [dict(r) for r in rows]

    def get_best_generation(self) -> dict | None:
        """Devuelve la generación aprobada con mayor delta_pct positivo."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    'SELECT * FROM generations WHERE approved=1 ORDER BY delta_pct DESC LIMIT 1'
                ).fetchone()
                return dict(row) if row else None
