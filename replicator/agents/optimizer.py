import time
import pathlib
from ollama import AsyncClient
from agents.base_agent import BaseAgent
from core.llm_config import MODEL

# Raíz del proyecto (scraper/) — límite para apply_improvement
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


class OptimizerAgent(BaseAgent):
    def __init__(self, ollama_host="http://localhost:11434"):
        super().__init__("Optimizer", "Performance & Efficiency")
        self.ollama_host = ollama_host

    async def think(self, target_file: str, func_name: str) -> str:
        """
        Lee el código y propone una versión refactorizada del archivo completo.
        Si func_name es un placeholder, el LLM elige qué refactorizar dentro del archivo.
        El código generado NUNCA se ejecuta automáticamente.
        """
        print(f"[INFO - {self.name}] Analizando {func_name} en {target_file}...")

        target = pathlib.Path(target_file).resolve()
        try:
            target.relative_to(_PROJECT_ROOT)
        except ValueError:
            print(f"[SECURITY - {self.name}] Ruta fuera del proyecto: {target_file}")
            return ""

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            full_code = f.read()

        # Estrategia: si el archivo es grande, extraer solo la funcion objetivo
        # para que llama3 pueda responder rapido (prompts cortos = respuestas rapidas)
        _MAX_SNIPPET_CHARS = 2500
        snippet = self._extract_function(full_code, func_name) if func_name else None
        if snippet and len(snippet) > _MAX_SNIPPET_CHARS:
            print(f"[INFO - {self.name}] Funcion '{func_name}' demasiado grande ({len(snippet)} chars > {_MAX_SNIPPET_CHARS}). Saltando.")
            return ""
        if snippet:
            code_for_llm = snippet
            print(f"[INFO - {self.name}] Funcion '{func_name}' extraida ({len(snippet)} chars).")
        else:
            # Sin funcion identificable: enviar el archivo entero pero acotado
            code_for_llm = full_code[:1500] if len(full_code) > 1500 else full_code

        placeholders = {"analizar_archivo", "(analizar manualmente)", "unknown", ""}
        is_generic = (func_name.strip() in placeholders
                      or func_name.strip().startswith("(")
                      or snippet is None)

        if is_generic:
            instruction = (
                "Refactoriza este codigo Python para que sea mas claro, conciso y eficiente. "
                "Mantén las mismas firmas publicas. "
                "NO añadas imports nuevos. NO uses eval/exec/open/os/subprocess/sys. "
                "Responde SOLO el codigo Python refactorizado, sin markdown."
            )
        else:
            instruction = (
                f"Refactoriza esta funcion '{func_name}' para que sea mas eficiente. "
                f"Mantén el mismo nombre y argumentos. "
                "NO añadas imports nuevos. NO uses eval/exec/open/os/subprocess/sys. "
                "Responde SOLO el codigo Python de la funcion, sin markdown."
            )

        prompt = f"{instruction}\n\nCodigo:\n{code_for_llm}"

        try:
            import asyncio as _aio
            client = AsyncClient(host=self.ollama_host)
            r = await _aio.wait_for(
                client.chat(
                    model=MODEL,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=180,
            )
            raw = r["message"]["content"].strip()
            # Limpiar markdown fences si los hay
            if "```" in raw:
                parts = raw.split("```")
                for i, part in enumerate(parts):
                    if i % 2 == 1:
                        return (part[6:].strip() if part.startswith("python") else part.strip())
            return raw
        except _aio.TimeoutError:
            print(f"[!] {self.name}: timeout interno (180s) — llama3 demasiado lento")
            return ""
        except Exception as e:
            print(f"[!] {self.name}: Error en think(): {type(e).__name__}: {e}")
            return ""

    @staticmethod
    def _extract_function(code: str, func_name: str) -> str | None:
        """Extrae el codigo fuente de una funcion concreta usando AST. None si no la encuentra."""
        if not func_name or func_name.startswith("("):
            return None
        try:
            import ast
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                    try:
                        return ast.get_source_segment(code, node)
                    except Exception:
                        # Fallback manual: extraer por numeros de linea
                        lines = code.splitlines()
                        end = getattr(node, "end_lineno", node.lineno + 20)
                        return "\n".join(lines[node.lineno - 1:end])
        except Exception:
            pass
        return None

    def benchmark(self, original_func, new_code: str, test_data) -> tuple[bool, float, float]:
        """
        Mide el rendimiento de la función original.
        El código LLM (new_code) NUNCA se ejecuta — exec() ha sido eliminado por seguridad.
        Devuelve (False, t_base, 0) para indicar que la mejora requiere revisión manual.
        """
        try:
            inicio = time.perf_counter()
            for _ in range(100):
                original_func(test_data)
            t_base = time.perf_counter() - inicio
        except Exception as e:
            print(f"[!] {self.name}: Error en benchmark original: {e}")
            return False, 0.0, 0.0

        print(
            f"[Optimizer] Baseline: {t_base:.4f}s. "
            "Sugerencia LLM registrada — requiere aprobación manual antes de aplicar."
        )
        return False, t_base, 0.0

    def apply_improvement(self, file_path: str, old_code: str, new_code: str) -> None:
        """
        Reemplaza old_code por new_code en file_path.
        Validaciones de seguridad: solo .py dentro del proyecto, solo archivos existentes.
        """
        target = pathlib.Path(file_path).resolve()

        # Bloqueo de path traversal
        try:
            target.relative_to(_PROJECT_ROOT)
        except ValueError:
            print(f"[SECURITY - {self.name}] BLOQUEADO: {file_path} está fuera del proyecto.")
            return

        # Solo archivos Python
        if target.suffix != ".py":
            print(f"[SECURITY - {self.name}] BLOQUEADO: solo se permiten archivos .py, recibido: {target.suffix}")
            return

        # El archivo debe existir (no crear archivos nuevos por error)
        if not target.is_file():
            print(f"[SECURITY - {self.name}] BLOQUEADO: el archivo no existe: {target}")
            return

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        new_content = content.replace(old_code, new_code)
        if new_content == content:
            print(f"[Optimizer] Sin cambios: old_code no encontrado en {target.name}")
            return

        with open(target, "w", encoding="utf-8", errors="replace") as f:
            f.write(new_content)
        print(f"[OK] {self.name}: {target.name} actualizado con mejora.")
