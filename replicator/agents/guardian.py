import ast
from agents.base_agent import BaseAgent
from ollama import AsyncClient
from core.llm_config import MODEL

# Nombres de funciones/builtins completamente prohibidos en código LLM
_FORBIDDEN_CALLS = {
    "eval", "exec", "compile", "__import__", "open",
    "getattr", "setattr", "delattr", "vars", "dir",
    "globals", "locals", "breakpoint", "input",
}

# Atributos que implican acceso a sistema de archivos o ejecución de procesos
_FORBIDDEN_ATTRS = {
    "system", "popen", "spawn", "execv", "execve", "execle",
    "remove", "rmdir", "unlink", "rmtree", "makedirs", "mkdir",
    "write", "writelines", "truncate",
}


_DANGEROUS_MODULES = {
    "os", "sys", "subprocess", "shutil", "pathlib", "socket", "ctypes",
    "pickle", "marshal", "builtins", "importlib", "asyncio.subprocess",
}


def _ast_scan(code: str, allowed_imports: set[str] | None = None) -> tuple[bool, str]:
    """
    Analiza el código con AST. Rechaza cualquier nodo peligroso.
    Esta verificación NO puede ser bypaseada con trucos de strings.
    allowed_imports: lista de modulos que el codigo original ya importaba (se permiten).
    Devuelve (es_seguro, motivo).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"SyntaxError al parsear: {e}"

    allowed = allowed_imports or set()

    for node in ast.walk(tree):
        # Bloquear imports: permitir solo los que ya estaban en el original Y no son peligrosos
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod = alias.name.split(".")[0]
                if mod in _DANGEROUS_MODULES:
                    return False, f"Modulo peligroso: import {alias.name}"
                if mod not in allowed:
                    return False, f"Import no autorizado: {alias.name} (no estaba en el original)"
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or "").split(".")[0]
            if mod in _DANGEROUS_MODULES:
                return False, f"Modulo peligroso: from {node.module}"
            if mod not in allowed:
                return False, f"Import no autorizado: from {node.module} (no estaba en el original)"

        # Bloquear llamadas a funciones prohibidas
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_CALLS:
                return False, f"Llamada prohibida: {func.id}()"
            if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_ATTRS:
                return False, f"Atributo prohibido en llamada: .{func.attr}()"

        # Bloquear acceso a atributos peligrosos (aunque no se llamen)
        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_ATTRS:
            return False, f"Acceso a atributo prohibido: .{node.attr}"

    return True, "AST limpio"


class GuardianAgent(BaseAgent):
    def __init__(self, ollama_host="http://localhost:11434"):
        super().__init__("Guardian", "Cybersecurity & Safety")
        self.ollama_host = ollama_host

    async def validate_code(self, code_proposed: str, original_code: str = "") -> tuple[bool, str]:
        """Auditoría de seguridad del código propuesto (AST + LLM).
        original_code: si se proporciona, los imports que ya existian en el original se permiten.
        """
        print(f"[INFO - {self.name}] Auditando código propuesto...")

        # Extraer imports del original (modulos que el codigo ya usaba)
        allowed = set()
        if original_code:
            try:
                orig_tree = ast.parse(original_code)
                for n in ast.walk(orig_tree):
                    if isinstance(n, ast.Import):
                        for alias in n.names:
                            allowed.add(alias.name.split(".")[0])
                    elif isinstance(n, ast.ImportFrom):
                        if n.module:
                            allowed.add(n.module.split(".")[0])
            except Exception:
                pass

        # 1. Análisis AST estático (no bypasseable con string tricks)
        safe, reason = _ast_scan(code_proposed, allowed_imports=allowed)
        if not safe:
            print(f"[WARNING - {self.name}] BLOQUEADO por AST: {reason}")
            return False, reason

        # 2. Segunda opinión del LLM (solo si pasa el AST)
        prompt = (
            "Actúa como experto en ciberseguridad. Analiza si este código Python es seguro "
            "para ser ejecutado. Busca puertas traseras, exfiltración de datos o inyección. "
            "Responde SOLO 'SAFE' si es seguro o 'DANGER: motivo' si no lo es.\n"
            f"Código:\n{code_proposed}"
        )
        try:
            client = AsyncClient(host=self.ollama_host)
            r = await client.chat(
                model=MODEL,
                messages=[{"role": "user", "content": prompt}],
                options={"timeout": 30},
            )
            veredicto = r["message"]["content"].strip().upper()
            if "SAFE" in veredicto and "DANGER" not in veredicto:
                print(f"[OK - {self.name}] VEREDICTO: CÓDIGO SEGURO. Sello Aegis aplicado.")
                return True, "Sello Aegis"
            else:
                print(f"[ERROR - {self.name}] VEREDICTO: PELIGRO DETECTADO: {veredicto}")
                return False, veredicto
        except Exception as e:
            return False, f"Error en auditoría LLM: {type(e).__name__}"
