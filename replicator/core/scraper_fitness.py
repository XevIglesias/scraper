"""
ScraperFitness: mide qué tan bien funciona el buscador de precios en la realidad.

Fitness 0-100 basado en datos reales de precios.db:
  - 50 pts: % de búsquedas que devolvieron un precio válido
  - 30 pts: reputación de tiendas (no confunde nuevo/reacondicionado)
  - 20 pts: % de tiendas sin errores recientes en memoria_errores
"""
import sqlite3
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_PRECIOS_DB  = _ROOT / "precios.db"
_REPLICATOR_DB = _ROOT / "replicator.db"


class ScraperFitness:

    def compute(self) -> dict:
        """
        Devuelve {fitness, tasa_exito, tasa_confianza_tiendas, tasa_sin_errores, detalle}.
        Si no hay datos suficientes, devuelve 50.0 como punto de partida neutral.
        """
        tasa_exito          = self._tasa_exito_precios()
        tasa_confianza      = self._tasa_confianza_tiendas()
        tasa_sin_errores    = self._tasa_sin_errores()

        fitness = round(
            tasa_exito       * 50 +
            tasa_confianza   * 30 +
            tasa_sin_errores * 20,
            2
        )

        return {
            "fitness":               fitness,
            "tasa_exito":            round(tasa_exito * 100, 1),        # % búsquedas con precio
            "tasa_confianza_tiendas":round(tasa_confianza * 100, 1),    # % tiendas fiables
            "tasa_sin_errores":      round(tasa_sin_errores * 100, 1),  # % dominios sin errores
        }

    # ── Componente 1: ¿cuántas búsquedas devuelven un precio válido? ──────────

    def _tasa_exito_precios(self) -> float:
        """Porcentaje de registros en historial_precios con precio > 0."""
        try:
            with sqlite3.connect(str(_PRECIOS_DB)) as conn:
                total = conn.execute("SELECT COUNT(*) FROM historial_precios").fetchone()[0]
                if total == 0:
                    return 0.5  # sin datos: neutral
                con_precio = conn.execute(
                    "SELECT COUNT(*) FROM historial_precios WHERE precio > 0"
                ).fetchone()[0]
                return con_precio / total
        except Exception:
            return 0.5

    # ── Componente 2: ¿las tiendas no confunden nuevo/reacondicionado? ────────

    def _tasa_confianza_tiendas(self) -> float:
        """
        Para cada tienda en reputacion_tiendas:
          - Si tiene > 3 ventas nuevas y 0 reacondicionados → fiable (1.0)
          - Si tiene reacondicionados siendo buscado como nuevo → penaliza
        """
        try:
            with sqlite3.connect(str(_PRECIOS_DB)) as conn:
                rows = conn.execute(
                    "SELECT veces_nuevo, veces_reacondicionado FROM reputacion_tiendas"
                ).fetchall()
            if not rows:
                return 0.5
            scores = []
            for nuevos, reacond in rows:
                total = nuevos + reacond
                if total == 0:
                    continue
                scores.append(nuevos / total)
            return sum(scores) / len(scores) if scores else 0.5
        except Exception:
            return 0.5

    # ── Componente 3: ¿cuántos dominios tienen errores recientes? ────────────

    def _tasa_sin_errores(self) -> float:
        """
        Mira memoria_errores de los últimos 7 días.
        Devuelve qué fracción de dominios activos NO tiene errores recientes.
        """
        try:
            with sqlite3.connect(str(_PRECIOS_DB)) as conn:
                # dominios distintos que han dado resultados
                dominios_activos = conn.execute(
                    "SELECT COUNT(DISTINCT tienda) FROM historial_precios"
                ).fetchone()[0]
                if dominios_activos == 0:
                    return 0.5
                # dominios con errores en los últimos 7 días
                dominios_con_error = conn.execute("""
                    SELECT COUNT(DISTINCT dominio) FROM memoria_errores
                    WHERE timestamp >= datetime('now', '-7 days')
                """).fetchone()[0]
            tasa_error = min(dominios_con_error / dominios_activos, 1.0)
            return 1.0 - tasa_error
        except Exception:
            return 0.5
