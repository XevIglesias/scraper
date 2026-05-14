import asyncio
import gc


class EvolutionOrchestrator:
    """
    Fachada que delega el ciclo evolutivo completo a EvolutionEngine.
    Se mantiene por compatibilidad con main.py y la UI.
    """

    def __init__(self, agents, db, ui):
        self.agents = agents
        self.db = db
        self.ui = ui
        self.current_phase = "IDLE"
        self._engine = None  # se inicializa lazy para evitar imports circulares

    def _get_engine(self):
        if self._engine is None:
            from core.evolution_engine import EvolutionEngine
            ollama_host = getattr(self.agents.get("optimizer"), "ollama_host", "http://localhost:11434")
            self._engine = EvolutionEngine(db=self.db, ui=self.ui, ollama_host=ollama_host)
        return self._engine

    async def run_cycle(self):
        """Delega al EvolutionEngine el ciclo completo Scout→Optimizer→Guardian→Tester→Benchmark→Approval."""
        engine = self._get_engine()
        await engine.run_cycle()
        gc.collect()
        self.update_status("IDLE")

    def update_status(self, text):
        self.current_phase = text
        print(f"[*] {text}")
        if self.ui:
            self.ui.after(0, lambda: self.ui.lbl_status.configure(text=text))
