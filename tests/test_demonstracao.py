"""Skills gravadas na tela: achar o texto do clique, montar os passos, senha nunca gravada, revisão e salvar."""
import json
import os

import pytest
from PIL import Image

from ghost.automacao import demonstracao as demo
from ghost.visao import olho


def palavras_tela():
    """Tela parecida com 'Pedidos de Venda' do Protheus: botões numa linha e um campo com rótulo."""
    def p(texto, x, y, linha, w=None):
        return {"texto": texto, "x": x, "y": y, "w": w or len(texto) * 8, "h": 14, "linha": linha}
    return [p("•", 20, 100, 0, 6), p("Incluir", 30, 100, 0), p("Alterar", 300, 100, 0), p("Outras", 600, 100, 0),
            p("Ações", 652, 100, 0), p("Cliente", 40, 200, 1), p("Usuário", 40, 300, 2), p("Senha", 40, 340, 3)]


def test_ancora_no_botao():
    a = olho.ancora_do_clique(palavras_tela(), 55, 106)
    assert a["texto"] == "Incluir" and abs(a["dx"]) < 10
    a = olho.ancora_do_clique(palavras_tela(), 640, 108)
    assert a["texto"] == "Outras Ações"


def test_ancora_campo_ao_lado_do_rotulo():
    a = olho.ancora_do_clique(palavras_tela(), 130, 206)      # clicou no campo vazio à direita de "Cliente"
    assert a["texto"] == "Cliente" and a["dx"] > 50


def test_sem_texto_perto():
    assert olho.ancora_do_clique(palavras_tela(), 900, 600) is None


def test_achar_texto_varias_palavras_e_simbolo_grudado():
    pal = palavras_tela()
    assert olho.achar_texto(pal, "outras ações")[0]["x"] == 600
    pal.append({"texto": "+Incluir", "x": 400, "y": 500, "w": 60, "h": 14, "linha": 9})
    assert len(olho.achar_texto(pal, "Incluir")) == 2
    assert olho.achar_texto(pal, "Incluir", perto=(410, 505))[0]["x"] == 400


def test_nome_base_da_janela():
    assert olho.nome_base("TOTVS Webapp - TOTVS Manufatura (TOTVS) 02.9.0005") == "TOTVS Webapp"
    assert olho.nome_base("Producao Outubro.xlsx - Excel") == "Excel"


def _foto():
    img = Image.new("RGB", (1000, 700), "white")
    img.info["origem"] = (100, 50)
    return img


def _eventos():
    j = {"exe": "chrome.exe", "titulo": "TOTVS Webapp - TOTVS Manufatura", "rect": (100, 50, 1000, 700), "classe": "x", "hwnd": 1}
    return [
        {"tipo": "clique", "t": 0.0, "x": 155, "y": 156, "botao": "left", "duplo": False, "janela": j, "foto": _foto()},
        {"tipo": "clique", "t": 1.0, "x": 230, "y": 256, "botao": "left", "duplo": False, "janela": j, "foto": _foto()},
        {"tipo": "digitar", "t": 2.0, "texto": "000371"},
        {"tipo": "clique", "t": 3.0, "x": 230, "y": 396, "botao": "left", "duplo": False, "janela": j, "foto": _foto()},
        {"tipo": "digitar", "t": 4.0, "texto": "minhaSenha123"},
        {"tipo": "tecla", "t": 5.0, "combo": "enter"},
    ]


def test_montar_passos_e_senha_nunca_gravada(tmp_path):
    passos = demo.montar_passos(_eventos(), ler=lambda foto: palavras_tela(), pasta=str(tmp_path))
    assert [p["acao"] for p in passos] == ["clicar", "clicar", "digitar", "clicar", "digitar", "tecla"]
    assert passos[0]["ancora"]["texto"] == "Incluir" and passos[0]["janela"]["base"] == "TOTVS Webapp"
    assert passos[1]["ancora"]["texto"] == "Cliente"
    assert passos[2]["texto"] == "000371" and not passos[2]["segredo"]
    assert passos[4]["segredo"] and passos[4]["texto"] == ""
    assert "minhaSenha123" not in json.dumps(passos)
    assert os.path.exists(tmp_path / passos[0]["recorte"])                  # miniatura para a revisão
    assert passos[3]["pausa"] == 1.0
    assert demo.descrever(passos[4]).startswith("Digitar a senha")


def test_revisao_variavel_remover_e_salvar(monkeypatch):
    from ghost.ia import skills
    passos = demo.montar_passos(_eventos(), ler=lambda foto: palavras_tela(), pasta=demo.PASTA_RASCUNHO)
    monkeypatch.setattr(demo, "_rascunho", {"passos": passos, "nome": "", "gatilho": "", "criado": "agora"})
    assert demo.marcar_variavel(3)                       # "000371" muda: pergunta "Qual Cliente?"
    assert passos[2]["variavel"] == "Cliente" and passos[2]["texto"] == ""
    assert not demo.marcar_variavel(1)                   # clique não é variável
    assert demo.remover_passo(6) and len(passos) == 5
    with pytest.raises(ValueError, match="nome"):
        demo.salvar()
    demo.definir_nome("Pedido do Hospital")
    s = demo.salvar()
    salva = skills.encontrar("pedido do hospital")
    assert salva and salva["tipo"] == "demonstracao" and salva["id"] == s["id"]
    assert os.path.isdir(os.path.join(demo.PASTA, s["pasta"])) and demo.rascunho() is None


def test_skill_descrita_com_senha_e_recusada(monkeypatch):
    from ghost.ia import skills

    class Resp:
        choices = [type("C", (), {"message": type("M", (), {"content": json.dumps({
            "nome": "login", "gatilhos": ["entrar"], "resumo": "",
            "passos": [{"ferramenta": "digitar_texto", "args": {"texto": "minha senha 123"}}]})})()})()]

    class Cliente:
        class chat:
            class completions:
                @staticmethod
                def create(**_):
                    return Resp()
    monkeypatch.setattr(skills, "_groq", lambda: Cliente)
    with pytest.raises(ValueError, match="senha"):
        skills.criar_por_descricao("abrir o protheus e digitar usuario e senha")


def test_ocr_com_letra_errada_ainda_acha():
    pal = [{"texto": "TOTVS", "x": 10, "y": 10, "w": 40, "h": 12, "linha": 0},
           {"texto": "Manutatura", "x": 55, "y": 10, "w": 80, "h": 12, "linha": 0}]
    assert olho.achar_texto(pal, "TOTVS Manufatura")
    assert not olho.achar_texto(pal, "Faturamento")


def _eventos_relatorio():
    j = {"exe": "chrome.exe", "titulo": "TOTVS Webapp - TOTVS Manufatura", "rect": (100, 50, 1000, 700), "classe": "x", "hwnd": 1}
    pop = {"exe": "chrome.exe", "titulo": "", "rect": (300, 300, 200, 100), "classe": "x", "hwnd": 2}

    def pal(foto):
        return [{"texto": "Da", "x": 40, "y": 200, "w": 20, "h": 14, "linha": 1},
                {"texto": "Data", "x": 64, "y": 200, "w": 30, "h": 14, "linha": 1},
                {"texto": "Até", "x": 40, "y": 260, "w": 24, "h": 14, "linha": 2},
                {"texto": "a", "x": 68, "y": 260, "w": 8, "h": 14, "linha": 2},
                {"texto": "Data", "x": 80, "y": 260, "w": 30, "h": 14, "linha": 2},
                {"texto": "Formato", "x": 40, "y": 30, "w": 60, "h": 14, "linha": 3},
                {"texto": "26", "x": 300, "y": 400, "w": 16, "h": 14, "linha": 4}]
    evs = [
        {"tipo": "clique", "t": 0, "x": 230, "y": 256, "botao": "left", "janela": j, "foto": _foto()},
        {"tipo": "digitar", "t": 1, "texto": "01/09/2026"},
        {"tipo": "clique", "t": 2, "x": 230, "y": 316, "botao": "left", "janela": j, "foto": _foto()},
        {"tipo": "digitar", "t": 3, "texto": "30/09/2026"},
        {"tipo": "clique", "t": 4, "x": 400, "y": 455, "botao": "left", "janela": j, "foto": _foto()},
        {"tipo": "clique", "t": 5, "x": 150, "y": 86, "botao": "left", "janela": pop, "foto": _foto()},
    ]
    return evs, pal


def test_datas_viram_campos_do_periodo():
    from datetime import date
    evs, pal = _eventos_relatorio()
    passos = demo.montar_passos(evs, ler=pal)
    d1, d2 = passos[1], passos[3]
    assert d1["tipo"] == "data" and d1["papel"] == "inicio" and d1["variavel"].startswith("Da Data")
    assert d2["tipo"] == "data" and d2["papel"] == "fim" and d1["formato"] == "%d/%m/%Y"
    assert passos[5]["popup"] and passos[5]["abs"] == [150, 86]
    assert any("calendário" in a for a in demo.avisos(passos))          # passo 5 clicou no dia "26"
    v = demo.valores_das_variaveis(passos, "relatório do mês passado", perguntar=lambda q: None, hoje=date(2026, 10, 27))
    assert v == {1: "01/09/2026", 3: "30/09/2026"}


def test_periodo_perguntado_uma_vez_so():
    from datetime import date
    evs, pal = _eventos_relatorio()
    passos = demo.montar_passos(evs, ler=pal)
    perguntas = []
    v = demo.valores_das_variaveis(passos, "relatório", perguntar=lambda q: perguntas.append(q) or "de 1 a 15 de outubro",
                                   hoje=date(2026, 10, 27))
    assert len(perguntas) == 1 and v == {1: "01/10/2026", 3: "15/10/2026"}
    with pytest.raises(demo.Parou):
        demo.valores_das_variaveis(passos, "relatório", perguntar=lambda q: None)


def test_variavel_volta_a_ser_fixa(monkeypatch):
    evs, pal = _eventos_relatorio()
    passos = demo.montar_passos(evs, ler=pal)
    monkeypatch.setattr(demo, "_rascunho", {"passos": passos, "nome": "", "gatilho": "", "criado": "", "avisos": []})
    assert demo.marcar_variavel(2, ligar=False)
    assert passos[1]["texto"] == "01/09/2026" and not passos[1]["variavel"]


def test_skill_com_datas_aceita_o_periodo_no_pedido(monkeypatch):
    from ghost.ia import skills
    evs, pal = _eventos_relatorio()
    skills.salvar({"id": "d_1", "tipo": "demonstracao", "nome": "faturamento por cliente",
                   "gatilhos": ["faturamento por cliente"], "passos": demo.montar_passos(evs, ler=pal)})
    skills.salvar({"id": "d_2", "tipo": "demonstracao", "nome": "abrir pedidos", "gatilhos": ["abrir pedidos"],
                   "passos": [{"acao": "tecla", "combo": "enter"}]})
    assert skills.encontrar("faturamento por cliente do mes passado")["id"] == "d_1"
    assert skills.encontrar("abrir pedidos de ontem") is None          # sem campo variável: só a frase exata
