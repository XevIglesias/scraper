"""
Sistema de métricas y función de fitness para el bucle evolutivo.
Usa análisis AST estático — nunca ejecuta código LLM directamente.
"""
import ast
import time
import pathlib
from typing import Callable


class MetricsTracker:
    """
    Mide la calidad del código mediante análisis AST + benchmarks de la función original.
    Pesos del fitness: rendimiento 60%, simplicidad 40%.
    """

    # ── Análisis estático ─────────────────────────────────────────────────────

    def measure_file(self, file_path: str) -> dict:
        """
        Analiza un .py con AST y devuelve métricas de calidad.
        Retorna dict con: loc, complexity, num_functions, num_classes, fitness.
        """
        try:
            source = pathlib.Path(file_path).read_text(encoding="utf-8", errors="replace")
            return self.measure_source(source)
        except Exception as e:
            print(f"[Metrics] Error midiendo {file_path}: {type(e).__name__}")
            return self._empty_metrics()

    def measure_source(self, source: str) -> dict:
        """
        Analiza código fuente Python (string) con AST.
        Retorna métricas de calidad sin ejecutar el código.
        """
        try:
            tree = ast.parse(source)
        except SyntaxError:
            return self._empty_metrics()

        loc = self._count_loc(source)
        complexity = self._cyclomatic_complexity(tree)
        num_functions = sum(1 for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
        num_classes = sum(1 for n in ast.walk(tree) if isinstance(n, ast.ClassDef))
        # Profundidad máxima de anidamiento
        nesting = self._max_nesting_depth(tree)

        metrics = {
            "loc": loc,
            "complexity": complexity,
            "num_functions": num_functions,
            "num_classes": num_classes,
            "nesting_depth": nesting,
        }
        metrics["fitness"] = self.fitness_score(metrics)
        return metrics

    # ── Benchmark de función real ─────────────────────────────────────────────

    def measure_runtime(self, func: Callable, test_input, n: int = 100) -> float:
        """
        Mide el tiempo medio de ejecución de func(test_input) en ms.
        Solo se usa para funciones EXISTENTES ya validadas, nunca para código LLM.
        """
        try:
            inicio = time.perf_counter()
            for _ in range(n):
                func(test_input)
            return ((time.perf_counter() - inicio) / n) * 1000
        except Exception as e:
            print(f"[Metrics] Error en benchmark de runtime: {type(e).__name__}")
            return 0.0

    # ── Fitness y delta ───────────────────────────────────────────────────────

    def fitness_score(self, metrics: dict) -> float:
        """
        Score combinado 0-100:
        - Menor complejidad → más puntos (hasta 50)
        - Menor LOC → más puntos (hasta 30)
        - Menor nesting → más puntos (hasta 20)
        """
        # Componente complejidad (0-50): 0 = muy complejo, 50 = simple
        complexity = metrics.get("complexity", 0)
        c_score = max(0.0, 50.0 - complexity * 1.5)

        # Componente LOC (0-30): 0 = muy largo, 30 = conciso
        loc = metrics.get("loc", 0)
        l_score = max(0.0, 30.0 - loc * 0.02)

        # Componente nesting (0-20): 0 = muy anidado, 20 = plano
        nesting = metrics.get("nesting_depth", 0)
        n_score = max(0.0, 20.0 - nesting * 4.0)

        return round(c_score + l_score + n_score, 2)

    def compute_delta(self, before: dict, after: dict) -> dict:
        """
        Calcula la diferencia de métricas antes/después de una propuesta.
        Retorna: {improved: bool, delta_pct: float, details: dict}
        """
        f_before = before.get("fitness", 0.0)
        f_after = after.get("fitness", 0.0)

        if f_before == 0:
            delta_pct = 0.0
        else:
            delta_pct = round(((f_after - f_before) / f_before) * 100, 2)

        details = {}
        for key in ("loc", "complexity", "nesting_depth"):
            b = before.get(key, 0)
            a = after.get(key, 0)
            if b != 0:
                details[f"{key}_delta"] = round(((a - b) / b) * 100, 1)

        return {
            "improved": f_after > f_before,
            "delta_pct": delta_pct,
            "fitness_before": f_before,
            "fitness_after": f_after,
            "details": details,
        }

    # ── Helpers AST ──────────────────────────────────────────────────────────

    @staticmethod
    def _count_loc(source: str) -> int:
        """Cuenta líneas de código excluyendo comentarios y líneas en blanco."""
        count = 0
        for line in source.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith("#"):
                count += 1
        return count

    @staticmethod
    def _cyclomatic_complexity(tree: ast.AST) -> int:
        """
        Complejidad ciclomática aproximada:
        1 base + 1 por cada: if, elif, for, while, except, with, assert, comprehension.
        """
        complexity = 1
        for node in ast.walk(tree):
            if isinstance(node, (
                ast.If, ast.For, ast.While, ast.ExceptHandler,
                ast.With, ast.Assert, ast.comprehension,
            )):
                complexity += 1
        return complexity

    @staticmethod
    def _max_nesting_depth(tree: ast.AST) -> int:
        """Profundidad máxima de anidamiento de bloques de control."""
        def _depth(node, current=0):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.With, ast.Try)):
                current += 1
            max_d = current
            for child in ast.iter_child_nodes(node):
                max_d = max(max_d, _depth(child, current))
            return max_d
        return _depth(tree)

    @staticmethod
    def _empty_metrics() -> dict:
        return {"loc": 0, "complexity": 0, "num_functions": 0, "num_classes": 0, "nesting_depth": 0, "fitness": 0.0}
