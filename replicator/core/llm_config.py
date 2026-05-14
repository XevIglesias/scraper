"""
Configuracion central del modelo LLM para REPLICATOR.
Cambiar aqui = cambia en todo el sistema.
"""
import os

# Modelo por defecto. Para refactor de codigo: qwen2.5-coder es muy superior a llama3.
# Override via env var: REPLICATOR_MODEL=otro-modelo
MODEL = os.environ.get("REPLICATOR_MODEL", "qwen2.5-coder:7b")

# Host de Ollama
OLLAMA_HOST = os.environ.get("REPLICATOR_OLLAMA_HOST", "http://localhost:11434")
