"""
CircuitBreaker: si un archivo falla N veces, se bloquea para el resto de la sesion.
Persiste en disco para que sobreviva entre reinicios (tras bug fix).
"""
import json
import pathlib
from datetime import datetime

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_STATE_FILE = _ROOT / "replicator" / ".circuit_state.json"
_MAX_FAILURES = 3   # despues de N fallos en el mismo archivo, se bloquea


class CircuitBreaker:
    def __init__(self):
        self._state: dict[str, dict] = self._load()

    # ── API publica ───────────────────────────────────────────────────────────

    def is_blocked(self, file_key: str) -> bool:
        entry = self._state.get(file_key)
        if entry is None:
            return False
        return entry.get("failures", 0) >= _MAX_FAILURES

    def record_failure(self, file_key: str, reason: str = ""):
        entry = self._state.setdefault(file_key, {"failures": 0, "reasons": []})
        entry["failures"] = entry.get("failures", 0) + 1
        reasons = entry.setdefault("reasons", [])
        reasons.append({"time": datetime.now().isoformat(timespec="seconds"), "reason": reason[:200]})
        entry["reasons"] = reasons[-5:]  # mantener solo los ultimos 5
        self._save()
        if entry["failures"] >= _MAX_FAILURES:
            print(f"[CircuitBreaker] BLOQUEADO: {file_key} ({entry['failures']} fallos)")

    def record_success(self, file_key: str):
        """Resetea el contador si el archivo finalmente tuvo exito."""
        if file_key in self._state:
            del self._state[file_key]
            self._save()

    def get_blocked_files(self) -> list[str]:
        return [k for k, v in self._state.items() if v.get("failures", 0) >= _MAX_FAILURES]

    def reset_all(self):
        """Borra todo el estado (uso manual al empezar una sesion fresca)."""
        self._state = {}
        if _STATE_FILE.exists():
            _STATE_FILE.unlink(missing_ok=True)

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        if not _STATE_FILE.exists():
            return {}
        try:
            return json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save(self):
        try:
            _STATE_FILE.write_text(json.dumps(self._state, indent=2), encoding="utf-8")
        except Exception:
            pass
