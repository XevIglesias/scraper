"""
BenchmarkAgent: compara métricas AST de código original vs propuesto.
Solo análisis estático — nunca ejecuta código.
"""
from dataclasses import dataclass, field
from agents.base_agent import BaseAgent
from core.metrics import MetricsTracker


@dataclass
class BenchmarkResult:
    is_improvement: bool
    delta_pct: float
    fitness_before: float
    fitness_after: float
    details: dict = field(default_factory=dict)


class BenchmarkAgent(BaseAgent):
    def __init__(self):
        super().__init__("Benchmark", "Static Code Analysis")
        self._metrics = MetricsTracker()

    def compare(self, original_source: str, proposed_source: str) -> BenchmarkResult:
        """
        Mide fitness AST de ambas versiones y calcula el delta.
        No ejecuta ningún código.
        """
        print(f"[INFO - {self.name}] Comparando métricas AST...")

        before = self._metrics.measure_source(original_source)
        after = self._metrics.measure_source(proposed_source)
        delta = self._metrics.compute_delta(before, after)

        result = BenchmarkResult(
            is_improvement=delta["improved"],
            delta_pct=delta["delta_pct"],
            fitness_before=delta["fitness_before"],
            fitness_after=delta["fitness_after"],
            details=delta["details"],
        )

        print(
            f"[{self.name}] fitness {result.fitness_before:.1f} → {result.fitness_after:.1f} "
            f"({'↑' if result.is_improvement else '↓'} {result.delta_pct:+.1f}%)"
        )
        self.learn(result)
        return result
