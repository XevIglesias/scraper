"""
TesterAgent: genera tests pytest con LLM y los ejecuta en replicator/tmp/ con timeout.
El código propuesto NUNCA se ejecuta directamente — solo los tests generados.
"""
import asyncio
import pathlib
import re
import subprocess
import sys
import uuid
from dataclasses import dataclass
from ollama import AsyncClient
from agents.base_agent import BaseAgent
from core.llm_config import MODEL


_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_TMP_DIR = _PROJECT_ROOT / "replicator" / "tmp"


@dataclass
class TestResult:
    passed: int
    failed: int
    errors: int
    output: str

    @property
    def all_pass(self) -> bool:
        return self.failed == 0 and self.errors == 0


class TesterAgent(BaseAgent):
    def __init__(self, ollama_host: str = "http://localhost:11434"):
        super().__init__("Tester", "Quality Assurance")
        self.ollama_host = ollama_host
        _TMP_DIR.mkdir(parents=True, exist_ok=True)

    async def generate_tests(self, proposed_code: str, func_name: str) -> str:
        """
        Llama al LLM para generar tests pytest para proposed_code.
        Devuelve el código de tests como string (puede estar vacío si falla).
        """
        print(f"[INFO - {self.name}] Generando tests para '{func_name}'...")

        prompt = (
            "Eres un experto en testing Python. Escribe tests pytest para la siguiente función.\n"
            "REGLAS ESTRICTAS:\n"
            "1. Usa SOLO la stdlib de Python (re, math, collections, etc.) — NO importes módulos externos.\n"
            "2. Define la función a testear inline dentro del archivo de test (copia el código que ves abajo).\n"
            "3. Escribe al menos 3 casos: normal, borde y valor inválido.\n"
            "4. Responde SOLO el código Python, sin explicaciones ni markdown.\n\n"
            f"Nombre de función: {func_name}\n"
            f"Código a testear:\n{proposed_code}"
        )

        try:
            client = AsyncClient(host=self.ollama_host)
            r = await client.chat(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"timeout": 60},
            )
            raw = r["message"]["content"].strip()
            return self._clean_code_fences(raw)
        except Exception as e:
            print(f"[{self.name}] Error generando tests: {type(e).__name__}")
            return ""

    def run_tests(self, test_code: str, timeout: int = 15) -> TestResult:
        """
        Escribe test_code en replicator/tmp/test_<uuid>.py,
        ejecuta pytest con timeout y devuelve TestResult.
        """
        if not test_code.strip():
            return TestResult(passed=0, failed=0, errors=1, output="Test code vacío.")

        test_file = _TMP_DIR / f"test_{uuid.uuid4().hex[:8]}.py"
        try:
            test_file.write_text(test_code, encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", str(test_file), "-v", "--tb=short", "--no-header"],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            output = result.stdout + result.stderr
            return self._parse_pytest_output(output)
        except subprocess.TimeoutExpired:
            return TestResult(passed=0, failed=0, errors=1, output=f"Timeout ({timeout}s) superado.")
        except Exception as e:
            return TestResult(passed=0, failed=0, errors=1, output=f"Error ejecutando pytest: {type(e).__name__}")
        finally:
            try:
                test_file.unlink(missing_ok=True)
            except Exception:
                pass

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_pytest_output(output: str) -> TestResult:
        """Extrae passed/failed/errors de la línea de resumen de pytest."""
        # Busca: "3 passed, 1 failed, 2 errors" en la última línea de resumen
        summary_pattern = re.compile(
            r"(?:(\d+) passed)?[,\s]*(?:(\d+) failed)?[,\s]*(?:(\d+) error(?:s)?)?"
        )
        passed = failed = errors = 0
        for line in reversed(output.splitlines()):
            if "passed" in line or "failed" in line or "error" in line:
                m = summary_pattern.search(line)
                if m:
                    passed = int(m.group(1) or 0)
                    failed = int(m.group(2) or 0)
                    errors = int(m.group(3) or 0)
                    break
        # Si no se encontró nada pero hay output, marcar como error
        if passed == 0 and failed == 0 and errors == 0 and output.strip():
            errors = 1
        return TestResult(passed=passed, failed=failed, errors=errors, output=output[:3000])

    @staticmethod
    def _clean_code_fences(text: str) -> str:
        if "```" in text:
            parts = text.split("```")
            for i, part in enumerate(parts):
                if i % 2 == 1:
                    if part.startswith("python"):
                        part = part[6:]
                    return part.strip()
        return text
