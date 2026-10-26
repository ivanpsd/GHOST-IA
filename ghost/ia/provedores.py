"""Fila de modelos de IA (todos com plano gratuito oficial). Cada provedor tem o SEU limite por minuto/dia:
quando um estoura (erro 429) ou falha, o Ghost passa para o próximo. Só entram os que têm chave no .env.

Chaves no .env (crie a conta no site do provedor e cole a chave):
  GROQ_API_KEY          (já usada)
  GEMINI_API_KEY        (já usada; aqui pelo endereço compatível, COM ferramentas)
  CEREBRAS_API_KEY      https://cloud.cerebras.ai
  OPENROUTER_API_KEY    https://openrouter.ai/keys      (só modelos ":free")
  MISTRAL_API_KEY       https://console.mistral.ai      (plano "Experiment", gratuito)
  GITHUB_MODELS_TOKEN   https://github.com/settings/tokens  (token com permissão "models")
O modelo de cada um pode ser trocado no .env: GEMINI_MODELO, CEREBRAS_MODELO, OPENROUTER_MODELO, MISTRAL_MODELO, GITHUB_MODELO.
Ordem da fila: FILA (abaixo). O Gemini "antigo" (sem ferramentas) continua como última reserva (em app.py)."""
import os

# (provedor, variável do .env com o modelo, modelo padrão)
FILA = [
    ("groq", None, "openai/gpt-oss-120b"),
    ("cerebras", "CEREBRAS_MODELO", "gpt-oss-120b"),
    ("groq", None, "openai/gpt-oss-20b"),
    ("gemini", "GEMINI_MODELO", "gemini-3.5-flash"),
    ("openrouter", "OPENROUTER_MODELO", "openai/gpt-oss-120b:free"),
    ("mistral", "MISTRAL_MODELO", "mistral-small-latest"),
    ("github", "GITHUB_MODELO", "openai/gpt-4.1-mini"),
]
EXTRAS = {   # provedores compatíveis com a API da OpenAI: chave no .env + endereço
    "gemini": ("GEMINI_API_KEY", "https://generativelanguage.googleapis.com/v1beta/openai/"),
    "cerebras": ("CEREBRAS_API_KEY", "https://api.cerebras.ai/v1"),
    "openrouter": ("OPENROUTER_API_KEY", "https://openrouter.ai/api/v1"),
    "mistral": ("MISTRAL_API_KEY", "https://api.mistral.ai/v1"),
    "github": ("GITHUB_MODELS_TOKEN", "https://models.github.ai/inference"),
}

_clientes = {}


def iniciar(cliente_groq):
    """Cria os clientes dos provedores com chave. Retorna os nomes ativos."""
    _clientes.clear()
    _clientes["groq"] = cliente_groq
    for nome, (var, url) in EXTRAS.items():
        chave = os.getenv(var, "").strip()
        if not chave:
            continue
        try:
            import httpx
            from openai import OpenAI
            _clientes[nome] = OpenAI(api_key=chave, base_url=url, max_retries=0,
                                     timeout=httpx.Timeout(8.0, connect=3.0))
        except Exception as e:
            print(f"\n[IA]: não consegui ligar o provedor {nome} ({e!r}).")
    return list(_clientes)


def rotas():
    """[(provedor, modelo)] na ordem de tentativa, só com os provedores ligados."""
    saida = []
    for prov, var, padrao in FILA:
        if prov in _clientes:
            r = (prov, (os.getenv(var, "").strip() if var else "") or padrao)
            if r not in saida:
                saida.append(r)
    return saida


def cliente(provedor):
    return _clientes[provedor]


def parametros(provedor, modelo, esforco):
    """Parâmetros extras que só alguns aceitam (raciocínio dos gpt-oss)."""
    if "gpt-oss" in modelo and provedor in ("groq", "cerebras", "openrouter"):
        return {"reasoning_effort": esforco}
    return {}


def nome(rota):
    prov, modelo = rota
    return modelo if prov == "groq" else f"{prov}:{modelo}"
