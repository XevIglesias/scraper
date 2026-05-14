from agents.base_agent import BaseAgent
from duckduckgo_search import DDGS
import asyncio

class InnovatorAgent(BaseAgent):
    def __init__(self):
        super().__init__("Innovator", "Features & Expansion")

    async def think(self, context="ecommerce price scraper"):
        print(f"[INFO - {self.name}] Investigando innovaciones reales en: {context}...")
        
        findings = []
        try:
            with DDGS() as ddgs:
                # Query negativa para evitar basura académica o diccionarios
                query = f'best features "price comparison scraper" 2025 -cambridge -dictionary -university -course'
                results = ddgs.text(query, max_results=10)
                
                # Filtro de relevancia manual
                keywords_relevantes = ["price", "tracking", "scraper", "ecommerce", "monitor", "competitor", "stock"]
                for r in results:
                    text_to_check = (r['title'] + r['body']).lower()
                    if any(kw in text_to_check for kw in keywords_relevantes):
                        findings.append(f"- {r['title']}: {r['href']}")
        except Exception as e:
            print(f"[!] Error en investigación DDGS: {e}")
            return "ERROR: No se pudo investigar en internet."

        if not findings:
            return "Sugerencia: Implementar un sistema de 'Proxy Rotation' para evitar bloqueos."

        summary = "TOP 3 FUNCIONES DE COMPETIDORES REALES:\n"
        summary += "\n".join(findings[:3])
        return summary

    async def act(self, target):
        print(f"[INFO - {self.name}] Proponiendo integración de: {target}")
        pass
