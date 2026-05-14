from agents.base_agent import BaseAgent

class ArchitectAgent(BaseAgent):
    def __init__(self):
        super().__init__("Architect", "Project Structure & Refactoring")

    async def think(self, context):
        print(f"[INFO - {self.name}] Evaluando modularidad del código...")
        return "ESTRUCTURA: OK"

    async def act(self, target):
        pass
