"""Fala sem loop e avisos de notificação sem repetir."""
import time

from ghost.ia.filtro_fala import FiltroFala


def test_ia_em_loop_fala_uma_vez():
    f = FiltroFala()
    falas = ["Qual painel deseja abrir, senhor?", "Deseja abrir o Painel de Controle do Windows, senhor?............",
             "Qual painel específico, senhor?.........", "Qual painel deseja abrir, senhor?...", "Entendido, senhor."]
    ditas = [x for x in (f.aceitar(t) for t in falas) if x]
    assert ditas == ["Qual painel deseja abrir, senhor?", "Entendido, senhor."]


def test_limite_de_frases():
    f = FiltroFala(max_frases=3)
    ditas = [f.aceitar(f"Item número {i} da lista de compras do mês.") for i in range(10)]
    assert sum(1 for d in ditas if d) <= 3


def test_notificacoes_do_mesmo_grupo_nao_repetem(monkeypatch):
    from ghost.servicos import notificacoes as n
    faladas = []
    monkeypatch.setattr(n, "_falar", faladas.append)
    monkeypatch.setattr(n, "_ocupado", lambda: False)
    monkeypatch.setattr(n, "_ultimo_anuncio", {})
    monkeypatch.setattr(n, "_pref", lambda chave, padrao: padrao)
    agora = time.time()
    for _ in range(4):
        n._pendentes.append({"t": agora, "app": "WhatsApp", "textos": ["Pedacinho Do Sol RJ", "oi"]})
    n._pendentes.append({"t": agora, "app": "WhatsApp", "textos": ["RH Pedacinho Do Sol", "aviso"]})
    n._anunciar()
    assert faladas == ["Senhor, 2 notificações. WhatsApp: Pedacinho Do Sol RJ, RH Pedacinho Do Sol."]
    n._pendentes.append({"t": time.time(), "app": "WhatsApp", "textos": ["Pedacinho Do Sol RJ", "de novo"]})
    n._anunciar()
    assert len(faladas) == 1                       # mesmo grupo há menos de 3 min: fica quieto
