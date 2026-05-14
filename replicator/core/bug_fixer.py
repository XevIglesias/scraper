"""
BugFixer: auto-reparación de bugs con Ollama.

Restricciones de seguridad absolutas:
  - NUNCA toca archivos de seguridad, el propio engine, ni archivos de control
  - Si aplica un fix, escribe .restart_needed para que el runner se relance
  - Guardian valida siempre antes de aplicar cualquier cambio
"""
import pathlib
import traceback as tb_module

from core.llm_config import MODEL

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# Archivos que NUNCA se pueden modificar automáticamente
_FORBIDDEN_FILES = {
    "replicator/core/security.py",
    "replicator/core/bug_fixer.py",
    "replicator/core/evolution_engine.py",
    "replicator/core/version_control.py",
    "replicator/core/governor.py",
    "replicator/agents/guardian.py",
    "replicator/night_runner.py",
    "replicator/main.py",
    ".env",
}

_RESTART_FLAG  = _ROOT / "replicator" / ".restart_needed"
_FIX_COUNT_FILE = _ROOT / "replicator" / ".fix_count"
_MAX_FILE_KB   = 100
_MAX_FIXES_PER_NIGHT = 3   # máximo de auto-reparaciones por sesión nocturna


class BugFixer:
    def __init__(self, db, ollama_host: str = "http://localhost:11434"):
        self.db = db
        self.ollama_host = ollama_host

    async def fix(self, exc: Exception, file_hint: str = ""):
        """Intenta reparar el archivo afectado. Nunca bloquea el proceso principal."""
        try:
            await self._fix(exc, file_hint)
        except Exception as inner:
            print(f"[BugFixer] Error interno (ignorado): {type(inner).__name__}: {inner}")

    async def _fix(self, exc: Exception, file_hint: str):
        # Límite anti-bucle: máximo N reparaciones por noche
        fix_count = self._get_fix_count()
        if fix_count >= _MAX_FIXES_PER_NIGHT:
            print(f"[BugFixer] Límite de {_MAX_FIXES_PER_NIGHT} reparaciones alcanzado. Sin más cambios.")
            return
        self._increment_fix_count()

        traceback_str = "".join(tb_module.format_exception(type(exc), exc, exc.__traceback__))
        target_path   = self._find_file(traceback_str, file_hint)

        print(f"\n[BugFixer] Reparacion {fix_count+1}/{_MAX_FIXES_PER_NIGHT}: {type(exc).__name__}: {exc}")

        if target_path is None:
            print(f"[BugFixer] No se identificó el archivo. Sin cambios.")
            self._log(str(exc), "archivo no identificado", approved=False)
            return

        rel = str(target_path.relative_to(_ROOT)).replace("\\", "/")
        print(f"[BugFixer] Archivo: {rel}")

        # Verificar que no es un archivo prohibido
        if rel in _FORBIDDEN_FILES or any(rel.endswith(f) for f in _FORBIDDEN_FILES):
            print(f"[BugFixer] ⛔ Archivo protegido — no se modifica nunca: {rel}")
            self._log(str(exc), f"archivo protegido: {rel}", approved=False)
            return

        if target_path.stat().st_size > _MAX_FILE_KB * 1024:
            print(f"[BugFixer] Archivo demasiado grande. Sin cambios.")
            self._log(str(exc), "archivo demasiado grande", approved=False)
            return

        original_code = target_path.read_text(encoding="utf-8", errors="replace")
        proposed_fix  = await self._ask_ollama(original_code, traceback_str)

        if not proposed_fix.strip():
            print(f"[BugFixer] Ollama no devolvió fix.")
            self._log(str(exc), "Ollama sin respuesta", approved=False)
            return

        # Guardian valida siempre
        from agents.guardian import GuardianAgent
        guardian = GuardianAgent(self.ollama_host)
        safe, reason = await guardian.validate_code(proposed_fix)

        if not safe:
            print(f"[BugFixer] Fix rechazado por Guardian: {reason}")
            self._log(str(exc), f"Guardian: {reason}", approved=False)
            return

        # Snapshot + aplicar
        from core.version_control import VersionControl
        vc = VersionControl()
        snapshot_id = vc.apply_patch(str(target_path), proposed_fix)
        print(f"[BugFixer] ✅ Fix aplicado en {target_path.name} (snapshot: {snapshot_id})")
        self._log(str(exc), f"fix aplicado OK, snapshot={snapshot_id}", approved=True)

        # Señal de reinicio: el runner lo detectará entre ciclos
        _RESTART_FLAG.write_text(
            f"bug_fixed:{rel}:{type(exc).__name__}", encoding="utf-8"
        )
        print(f"[BugFixer] 🔁 Señal de reinicio escrita — el proceso se relanzará.")

    async def _ask_ollama(self, code: str, traceback_str: str) -> str:
        import asyncio
        from ollama import AsyncClient
        prompt = (
            "Eres un experto en Python. El siguiente código produjo este error:\n\n"
            f"ERROR:\n{traceback_str[-1200:]}\n\n"
            f"CÓDIGO:\n{code[:2500]}\n\n"
            "Escribe el código Python COMPLETO corregido.\n"
            "REGLAS ESTRICTAS: NO añadas imports nuevos. "
            "NO uses eval, exec, open, os, subprocess, sys. "
            "Responde SOLO el código, sin explicaciones ni markdown."
        )
        try:
            client = AsyncClient(host=self.ollama_host)
            r = await asyncio.wait_for(
                client.chat(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=90,
            )
            raw = r["message"]["content"].strip()
            if "```" in raw:
                parts = raw.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 1:
                        return part[6:].strip() if part.startswith("python") else part.strip()
            return raw
        except Exception as e:
            print(f"[BugFixer] Ollama error: {type(e).__name__}")
            return ""

    def _find_file(self, traceback_str: str, hint: str) -> pathlib.Path | None:
        if hint:
            p = pathlib.Path(hint).resolve()
            if p.is_file() and p.suffix == ".py":
                try:
                    p.relative_to(_ROOT)
                    return p
                except ValueError:
                    pass
        for line in traceback_str.splitlines():
            if 'File "' in line and '.py"' in line:
                try:
                    path_str = line.split('File "')[1].split('"')[0]
                    p = pathlib.Path(path_str).resolve()
                    if p.is_file() and p.suffix == ".py":
                        p.relative_to(_ROOT)
                        return p
                except Exception:
                    continue
        return None

    def _get_fix_count(self) -> int:
        try:
            return int(_FIX_COUNT_FILE.read_text().strip())
        except Exception:
            return 0

    def _increment_fix_count(self):
        try:
            _FIX_COUNT_FILE.write_text(str(self._get_fix_count() + 1))
        except Exception:
            pass

    def _log(self, error_msg: str, reason: str, approved: bool):
        try:
            self.db.store_generation(
                phase="bug_fixed" if approved else "bug_unfixed",
                target_file="auto",
                func_name="bug_fixer",
                approved=approved,
                notes=f"{reason} | {error_msg}"[:200],
            )
        except Exception:
            pass
