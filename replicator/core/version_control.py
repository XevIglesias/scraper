"""
Sistema de snapshots de ficheros .py para el bucle evolutivo.
No usa git ni subprocess — solo shutil + pathlib.
"""
import json
import shutil
import pathlib
from datetime import datetime


_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent  # scraper/
_SNAPSHOTS_DIR = _PROJECT_ROOT / "replicator" / "snapshots"
_MAX_SNAPSHOTS = 10

# Patrones a excluir del snapshot
_EXCLUDE_DIRS = {"__pycache__", "snapshots", ".venv", "venv", "env", "dist", "build"}
_INCLUDE_EXTS = {".py"}


class VersionControl:
    """
    Gestión de snapshots del proyecto.
    Cada snapshot es una copia de todos los .py en un subdirectorio con timestamp.
    """

    def __init__(self):
        _SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── API pública ───────────────────────────────────────────────────────────

    def snapshot(self, label: str = "auto") -> str:
        """
        Copia todos los .py del proyecto a un nuevo snapshot.
        Devuelve el snapshot_id (nombre del directorio).
        """
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_label = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[:30]
        snapshot_id = f"{ts}_{safe_label}"
        dest = _SNAPSHOTS_DIR / snapshot_id
        dest.mkdir(parents=True, exist_ok=True)

        files_saved = 0
        for src_file in self._iter_py_files(_PROJECT_ROOT):
            rel = src_file.relative_to(_PROJECT_ROOT)
            dst_file = dest / rel
            dst_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_file, dst_file)
            files_saved += 1

        # Guardar metadatos
        meta = {
            "snapshot_id": snapshot_id,
            "timestamp": datetime.now().isoformat(),
            "label": label,
            "files": files_saved,
        }
        (dest / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        print(f"[VersionControl] Snapshot '{snapshot_id}' guardado ({files_saved} archivos)")
        self.cleanup_old()
        return snapshot_id

    def rollback(self, snapshot_id: str) -> bool:
        """
        Restaura el proyecto al estado del snapshot dado.
        Devuelve True si se restauró correctamente.
        """
        src = _SNAPSHOTS_DIR / snapshot_id
        if not src.is_dir():
            print(f"[VersionControl] ERROR: Snapshot '{snapshot_id}' no encontrado.")
            return False

        restored = 0
        for snap_file in src.rglob("*.py"):
            rel = snap_file.relative_to(src)
            dst = _PROJECT_ROOT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(snap_file, dst)
            restored += 1

        print(f"[VersionControl] Rollback completado: {restored} archivos restaurados desde '{snapshot_id}'")
        return True

    def apply_patch(self, file_path: str, new_content: str) -> str:
        """
        Hace snapshot del estado actual, luego escribe new_content en file_path.
        Devuelve el snapshot_id creado (para rollback si el usuario rechaza).
        """
        target = pathlib.Path(file_path).resolve()

        # Seguridad: solo .py dentro del proyecto
        try:
            target.relative_to(_PROJECT_ROOT)
        except ValueError:
            raise ValueError(f"Ruta fuera del proyecto: {file_path}")
        if target.suffix != ".py":
            raise ValueError(f"Solo se permiten archivos .py: {file_path}")
        if not target.is_file():
            raise FileNotFoundError(f"Archivo no existe: {file_path}")

        func_name = pathlib.Path(file_path).stem
        snapshot_id = self.snapshot(label=f"pre_{func_name}")

        target.write_text(new_content, encoding="utf-8")
        print(f"[VersionControl] Patch aplicado a {target.name} (snapshot: {snapshot_id})")
        return snapshot_id

    def list_snapshots(self) -> list[dict]:
        """Lista todos los snapshots con sus metadatos, del más reciente al más antiguo."""
        result = []
        for d in sorted(_SNAPSHOTS_DIR.iterdir(), reverse=True):
            if not d.is_dir():
                continue
            meta_file = d / "_meta.json"
            if meta_file.exists():
                try:
                    meta = json.loads(meta_file.read_text(encoding="utf-8"))
                    result.append(meta)
                except Exception:
                    result.append({"snapshot_id": d.name, "timestamp": "", "label": "?", "files": 0})
        return result

    def cleanup_old(self) -> None:
        """Elimina snapshots más antiguos si superan MAX_SNAPSHOTS."""
        dirs = sorted(
            [d for d in _SNAPSHOTS_DIR.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        for old in dirs[_MAX_SNAPSHOTS:]:
            try:
                shutil.rmtree(old)
                print(f"[VersionControl] Snapshot antiguo eliminado: {old.name}")
            except Exception as e:
                print(f"[VersionControl] No se pudo eliminar {old.name}: {type(e).__name__}")

    # ── Helpers privados ──────────────────────────────────────────────────────

    @staticmethod
    def _iter_py_files(root: pathlib.Path):
        """Itera recursivamente todos los .py del proyecto, excluyendo dirs irrelevantes."""
        for path in root.rglob("*.py"):
            # Excluir directorios bloqueados en cualquier parte del path
            if any(part in _EXCLUDE_DIRS for part in path.parts):
                continue
            yield path
