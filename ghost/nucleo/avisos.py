"""
GHOST - Central de avisos: tudo o que o Ghost fala SEM o senhor ter pedido (mensagens, aparelho novo na rede,
servidor caiu, lembrete, tarefa concluída...) passa por aqui, numa fila só.

Regras (para não atropelar nada):
- Nunca fala enquanto: o senhor conversa com o Ghost, o Ghost responde, há uma pergunta/confirmação esperando
  resposta, a janela de resposta está aberta, ou o F9 está apertado.
- Espera o ambiente ficar em SILÊNCIO (ninguém falando perto do microfone) — assim não fala por cima de uma
  conversa sua com outra pessoa. Quanto mais importante o aviso, menos silêncio exige.
- Avisos acumulados saem juntos numa frase só, do mais importante para o menos.
- Aviso comum velho demais é descartado (fica só no painel). Aviso crítico, se esperar demais, fala assim que o
  Ghost terminar o que estiver falando.
- Enquanto fala um aviso, voz alta na sala NÃO o interrompe (só "Ghost" ou F9) — para não cortar no meio.
"""
import threading
import time

# prioridade: (silêncio exigido em s, espera máxima em s até falar mesmo sem silêncio, validade em s)
PRIORIDADES = {
    "critica": (1.5, 90, None),        # servidor/internet caiu
    "alta": (3.0, 300, 3600),          # lembrete, tarefa concluída
    "normal": (6.0, None, 300),        # WhatsApp, aparelho novo, alertas de rotina
}
ORDEM = {"critica": 0, "alta": 1, "normal": 2}
MAX_JUNTOS = 3
INTERVALO_S = 0.5

_fila = []
_trava = threading.Lock()
_falar = None
_livre = None              # livre(segundos_de_silencio) -> True se pode falar agora
_ghost_falando = None      # ghost_falando() -> True enquanto sai áudio
_thread = None


def anunciar(texto, prioridade="normal", chave=None):
    """Põe um aviso na fila. chave: avisos com a mesma chave substituem o anterior ainda não falado."""
    texto = (texto or "").strip()
    if not texto:
        return
    prioridade = prioridade if prioridade in PRIORIDADES else "normal"
    with _trava:
        if chave:
            _fila[:] = [a for a in _fila if a["chave"] != chave]
        _fila.append({"t": time.time(), "texto": texto, "prioridade": prioridade, "chave": chave})
    print(f"\n[AVISO {prioridade}]: na fila: {texto}")


def pendentes():
    with _trava:
        return [dict(a) for a in _fila]


def _juntar(itens):
    """Vários avisos -> uma fala só: "Senhor, 2 avisos. O servidor caiu. WhatsApp: Leonard." """
    if len(itens) == 1:
        return itens[0]["texto"]
    partes = []
    for a in itens:
        t = a["texto"].strip()
        if t.lower().startswith("senhor,"):
            t = t[7:].strip()
        partes.append((t[:1].upper() + t[1:]).rstrip(".") + ".")
    return f"Senhor, {len(itens)} avisos. " + " ".join(partes)


def escolher(agora, livre, falando):
    """Decide o que falar agora (função pura, testável). Devolve (lista de avisos a falar, lista de vencidos)."""
    with _trava:
        vencidos = [a for a in _fila if PRIORIDADES[a["prioridade"]][2] and agora - a["t"] > PRIORIDADES[a["prioridade"]][2]]
        for a in vencidos:
            _fila.remove(a)
        if not _fila:
            return [], vencidos
        _fila.sort(key=lambda a: (ORDEM[a["prioridade"]], a["t"]))
        primeiro = _fila[0]
        silencio, espera_max, _ = PRIORIDADES[primeiro["prioridade"]]
        pode = livre(silencio) or (espera_max is not None and agora - primeiro["t"] > espera_max and not falando())
        if not pode:
            return [], vencidos
        juntos = _fila[:MAX_JUNTOS]
        del _fila[:MAX_JUNTOS]
        return juntos, vencidos


def _laco():
    while True:
        time.sleep(INTERVALO_S)
        try:
            falar_agora, vencidos = escolher(time.time(), _livre, _ghost_falando)
            for a in vencidos:
                print(f"\n[AVISO]: descartado por ficar velho (o senhor estava ocupado): {a['texto']}")
            if falar_agora and _falar:
                _falar(_juntar(falar_agora))
        except Exception as e:
            print(f"\n[AVISO]: erro na central de avisos ({e!r}).")


def iniciar(falar, livre, ghost_falando):
    """falar(texto): fala como AVISO (não interrompível por voz alta). livre(s): pode falar agora com s de silêncio?"""
    global _falar, _livre, _ghost_falando, _thread
    _falar, _livre, _ghost_falando = falar, livre, ghost_falando
    if _thread is None:
        _thread = threading.Thread(target=_laco, daemon=True, name="avisos")
        _thread.start()


def para(prioridade="normal"):
    """Função 'falar' para entregar a um serviço: tudo o que ele falar vira aviso com essa prioridade."""
    return lambda texto: anunciar(texto, prioridade)
