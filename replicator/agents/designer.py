from agents.base_agent import BaseAgent

class DesignerAgent(BaseAgent):
    def __init__(self):
        super().__init__("Designer", "UI/UX & Aesthetics")

    async def think(self, context):
        print(f"[INFO - {self.name}] Analizando paletas de colores tendencia...")
        return "ESTILO: Proponer modo 'Graphite Neon'"

    async def act(self, target):
        pass
