import sqlite3
import os
import threading
from datetime import datetime
from urllib.parse import urlparse

class PreciosDB:
    def __init__(self, db_path="precios.db"):
        self.db_path = db_path
        self._lock = threading.Lock()
        self._inicializar()

    def _inicializar(self):
        """Crea las tablas si no existen."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS historial_precios (
                        id          INTEGER PRIMARY KEY AUTOINCREMENT,
                        producto    TEXT,
                        tienda      TEXT,
                        url         TEXT,
                        precio      REAL,
                        envio       REAL,
                        total       REAL,
                        en_stock    BOOLEAN,
                        timestamp   DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS alertas (
                        id              INTEGER PRIMARY KEY AUTOINCREMENT,
                        producto        TEXT,
                        precio_objetivo REAL,
                        activa          BOOLEAN DEFAULT 1,
                        creada          DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS reputacion_tiendas (
                        dominio TEXT PRIMARY KEY,
                        veces_reacondicionado INTEGER DEFAULT 0,
                        veces_nuevo INTEGER DEFAULT 0,
                        ultima_actualizacion DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                ''')
                cursor.execute('''
                    CREATE TABLE IF NOT EXISTS parsers_ia (
                        dominio TEXT PRIMARY KEY,
                        selector_precio TEXT,
                        selector_nombre TEXT,
                        aciertos INTEGER DEFAULT 0,
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
                conn.commit()

    @staticmethod
    def _dominio_desde_url(url: str) -> str:
        """Extrae el dominio de una URL de forma segura usando urlparse."""
        try:
            h = urlparse(url).hostname or ""
            return h[4:] if h.startswith("www.") else h
        except Exception:
            return ""

    def guardar_resultado(self, r: dict):
        """Guarda un resultado de búsqueda en el historial."""
        tienda = self._dominio_desde_url(r.get("url", ""))
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO historial_precios (producto, tienda, url, precio, envio, total, en_stock)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    r.get("nombre_detectado"),
                    tienda,
                    r.get("url"),
                    r.get("precio_eur"),
                    r.get("envio_eur"),
                    r.get("total_eur"),
                    1 if r.get("stock_label", "").startswith("✅") else 0
                ))
                conn.commit()

    def obtener_minimo_historico(self, producto: str) -> dict | None:
        """Devuelve el precio mínimo histórico para un producto (por nombre parcial)."""
        # Usar primera palabra para búsqueda parcial, escapando wildcards SQL
        first_word = producto.strip().split()[0] if producto.strip() else producto
        safe_word = first_word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT total, timestamp, tienda FROM historial_precios
                    WHERE producto LIKE ? ESCAPE '\\' AND total > 1.0
                    ORDER BY total ASC LIMIT 1
                ''', (f"%{safe_word}%",))
                res = cursor.fetchone()
                if res:
                    return {"total": res[0], "fecha": res[1], "tienda": res[2]}
        return None

    def crear_alerta(self, producto: str, precio_objetivo: float):
        """Crea una nueva alerta de precio."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO alertas (producto, precio_objetivo)
                    VALUES (?, ?)
                ''', (producto, precio_objetivo))
                conn.commit()

    def comprobar_alertas(self, producto: str, precio_actual: float) -> list[dict]:
        """Comprueba si el precio actual activa alguna alerta."""
        alertas_activadas = []
        # Escapar wildcards del producto antes de usarlo en LIKE
        safe_producto = producto.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT id, precio_objetivo FROM alertas
                    WHERE activa = 1 AND ? LIKE '%' || producto || '%' ESCAPE '\\' AND ? <= precio_objetivo
                ''', (safe_producto, precio_actual))
                for row in cursor.fetchall():
                    alertas_activadas.append({"id": row[0], "objetivo": row[1]})
        return alertas_activadas

    def borrar_historial(self):
        """Elimina todos los datos del historial."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('DELETE FROM historial_precios')
                conn.commit()

    def registrar_error_aprendizaje(self, dominio: str, url: str, tipo_error: str, leccion: str = ""):
        """Guarda un error para que la IA aprenda de él."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO memoria_errores (dominio, url, tipo_error, leccion)
                    VALUES (?, ?, ?, ?)
                ''', (dominio, url, tipo_error, leccion))
                conn.commit()

    def obtener_lecciones_dominio(self, dominio: str) -> list[str]:
        """Recupera lecciones aprendidas para un dominio específico."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT leccion FROM memoria_errores WHERE dominio = ? AND leccion != ""', (dominio,))
                return [r[0] for r in cursor.fetchall()]

    def obtener_lecciones_globales(self) -> list[str]:
        """Recupera las lecciones más importantes de toda la base de datos."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    SELECT leccion FROM memoria_errores
                    WHERE leccion != ""
                    GROUP BY leccion
                    ORDER BY COUNT(*) DESC LIMIT 5
                ''')
                return [r[0] for r in cursor.fetchall()]

    def registrar_recompensa(self, url: str, valor: int):
        """Registra feedback del usuario (+1 útil, -1 no útil)."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                try:
                    cursor.execute('ALTER TABLE historial_precios ADD COLUMN recompensa INTEGER DEFAULT 0')
                except Exception:
                    pass
                cursor.execute('UPDATE historial_precios SET recompensa = recompensa + ? WHERE url = ?', (valor, url))
                conn.commit()

    def registrar_reputacion(self, dominio: str, es_reacondicionado: bool):
        """Anota si hemos encontrado un producto nuevo o usado en un dominio."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO reputacion_tiendas (dominio, veces_reacondicionado, veces_nuevo)
                    VALUES (?, ?, ?)
                    ON CONFLICT(dominio) DO UPDATE SET
                        veces_reacondicionado = veces_reacondicionado + excluded.veces_reacondicionado,
                        veces_nuevo = veces_nuevo + excluded.veces_nuevo,
                        ultima_actualizacion = CURRENT_TIMESTAMP
                ''', (dominio, 1 if es_reacondicionado else 0, 0 if es_reacondicionado else 1))
                conn.commit()

    def es_tienda_bloqueada(self, dominio: str, buscar_nuevo: bool) -> bool:
        """
        Si buscamos 'Nuevo' y la tienda tiene historial de solo reacondicionados, la bloqueamos.
        """
        if not buscar_nuevo:
            return False
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT veces_reacondicionado, veces_nuevo FROM reputacion_tiendas WHERE dominio = ?',
                    (dominio,)
                )
                res = cursor.fetchone()
                if res:
                    v_reacond, v_nuevo = res
                    if v_reacond >= 3 and v_nuevo == 0:
                        return True
        return False

    def registrar_parser_ia(self, dominio: str, sel_precio: str, sel_nombre: str):
        """Guarda selectores aprendidos por la IA."""
        if not sel_precio or not sel_nombre:
            return
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute('''
                    INSERT INTO parsers_ia (dominio, selector_precio, selector_nombre, aciertos)
                    VALUES (?, ?, ?, 1)
                    ON CONFLICT(dominio) DO UPDATE SET
                        selector_precio = excluded.selector_precio,
                        selector_nombre = excluded.selector_nombre,
                        aciertos = aciertos + 1,
                        ultima_actualizacion = CURRENT_TIMESTAMP
                ''', (dominio, sel_precio, sel_nombre))
                conn.commit()

    def obtener_parser_ia(self, dominio: str) -> dict | None:
        """Recupera selectores aprendidos para un dominio."""
        with self._lock:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    'SELECT selector_precio, selector_nombre FROM parsers_ia WHERE dominio = ?',
                    (dominio,)
                )
                res = cursor.fetchone()
                if res:
                    return {"selector_precio": res[0], "selector_nombre": res[1]}
        return None
