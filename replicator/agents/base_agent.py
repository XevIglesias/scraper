class BaseAgent:
    def __init__(self, name, role):
        self.name = name
        self.role = role
        self.knowledge_base = []

    async def think(self, context):
        """Lógica de razonamiento del agente (Asíncrona)."""
        pass

    async def act(self, target):
        """Acción física (Asíncrona)."""
        pass

    def learn(self, result):
        """Almacenar el resultado."""
        self.knowledge_base.append(result)
