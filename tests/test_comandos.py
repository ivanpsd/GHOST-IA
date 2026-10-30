"""Frases faladas -> o que o Ghost entende (sem executar nada)."""
import pytest

from tests.conftest import windows

pytestmark = windows


@pytest.fixture(scope="module")
def app():
    from ghost import app
    return app


@pytest.fixture(scope="module")
def auto():
    from ghost.automacao import automacoes
    return automacoes


@pytest.mark.parametrize("frase", ["tchau ghost", "boa noite, Ghost", "Ghost, pode descansar", "até amanhã ghost valeu"])
def test_frases_que_fazem_dormir(app, auto, frase):
    assert app.FRASE_DORMIR.fullmatch(auto.normalizar(frase))


@pytest.mark.parametrize("frase", ["oi ghost abre o excel", "boa noite pessoal da reunião", "ghost qual a previsão do tempo",
                                   "tchau tchau para o problema"])
def test_frases_comuns_nao_mudam_o_modo(app, auto, frase):
    n = auto.normalizar(frase)
    assert not app.FRASE_DORMIR.fullmatch(n)


@pytest.mark.parametrize("frase", ["Precisa de mais alguma coisa, senhor?", "Posso ajudar em algo mais?",
                                   "Mais alguma coisa?", "Senhor, deseja mais algum detalhe?"])
def test_oferta_generica_e_cortada(app, frase):
    assert app._oferta_generica(frase)


@pytest.mark.parametrize("frase", ["Quer que eu abra a planilha de produção?", "Para qual contato envio, senhor?",
                                   "A reunião é às 14h ou às 15h?"])
def test_pergunta_util_passa(app, frase):
    assert not app._oferta_generica(frase)


@pytest.mark.parametrize("frase,contato,msg", [
    ("mande mensagem para a Deborah dizendo que a reunião mudou", "deborah", "que a reunião mudou"),
    ("Ghost, envie uma mensagem no whatsapp para Leonard dizendo bom dia", "leonard", "bom dia"),
])
def test_mensagem_whatsapp(auto, frase, contato, msg):
    m = auto.REGEX_MENSAGEM.match(frase)
    assert m and m.group("contato").strip().lower() == contato and msg in m.group("msg")


@pytest.mark.parametrize("frase", ["você lembra o que eu escrevi para a Deborah que a reunião mudou?",
                                   "o que a Deborah mandou dizendo sobre a reunião?"])
def test_pergunta_nao_vira_mensagem(auto, frase):
    assert not auto.REGEX_MENSAGEM.match(frase)


def test_ditado(auto):
    assert auto.REGEX_DITADO.match("digite bom dia equipe").group("t") == "bom dia equipe"
    assert auto.REGEX_DITADO.match("escreva o texto reunião às 14h").group("t") == "reunião às 14h"


def test_confirmacao_sim_nao(auto):
    assert "sim" in auto.SIM and "pode" in auto.SIM
    assert "nao" in auto.NAO and "cancela" in auto.NAO
    assert not (auto.SIM & auto.NAO)


@pytest.mark.parametrize("frase,esperado", [
    ("ghost abrir painel", "abrir"), ("mostra o painel", "abrir"), ("fecha o painel", "fechar"),
    ("abre seus indicadores", "abrir"), ("exportar indicadores", "exportar"), ("eu falei abrir painel", "abrir"),
    ("abra o painel de controle", None), ("me mostra os indicadores de produção da planilha de outubro", None),
])
def test_comandos_do_painel(auto, monkeypatch, frase, esperado):
    from ghost.nucleo import painel
    feito = []
    monkeypatch.setattr(painel, "abrir_janela", lambda: feito.append("abrir") or True)
    monkeypatch.setattr(painel, "fechar_janela", lambda: feito.append("fechar"))
    monkeypatch.setattr(painel, "exportar", lambda: feito.append("exportar") or "C:/x.xlsx")
    monkeypatch.setattr(auto, "em_segundo_plano", lambda f, *a: f(*a))
    tratou = auto._tratar_hud(auto.normalizar(frase), lambda t: None)
    assert (feito[0] if feito else None) == esperado
    assert tratou == (esperado is not None)


@pytest.mark.parametrize("frase,sensivel", [
    ("mande mensagem para a Deborah dizendo que a reunião mudou", True),
    ("digite bom dia equipe", True), ("aperte enter", True), ("desligar o computador", True),
    ("fecha o excel", True),
    ("resumo do dia", False), ("quais são meus lembretes?", False), ("sim", False), ("não", False),
    ("como está o computador?", False),
])
def test_acoes_sensiveis_do_celular(auto, frase, sensivel):
    assert bool(auto.comando_sensivel(frase)) == sensivel


def test_pedidos_da_planta_das_cameras():
    from ghost.automacao.automacoes import normalizar, pediu_hud_cameras
    sim = ["Abra o painel das câmeras.", "Abra o painel das câmeras, por gentileza.", "abre as câmeras",
           "Você consegue abrir o modelo 3D das câmeras?", "Está dentro das suas automações, que é a câmera HUD. Abra.",
           "abrir planta das câmeras", "mostra as câmeras da empresa", "câmeras de segurança"]
    nao = ["abra a câmera", "ligar a câmera", "quantas câmeras estão com movimento?", "câmeras apenas",
           "qual câmera tem alguém agora?"]
    assert all(pediu_hud_cameras(normalizar(f)) for f in sim), [f for f in sim if not pediu_hud_cameras(normalizar(f))]
    assert not any(pediu_hud_cameras(normalizar(f)) for f in nao), [f for f in nao if pediu_hud_cameras(normalizar(f))]


def test_ensinar_comando_por_voz():
    from ghost.automacao.automacoes import ler_ensino, traduzir_ensinado
    assert ler_ensino("Quando eu falar painel das câmeras, abra a planta das câmeras") == \
        ("painel das cameras", "abra a planta das cameras")
    assert ler_ensino("sempre que eu disser o relatório, faça exportar indicadores") == ("relatorio", "exportar indicadores")
    assert ler_ensino("quando eu falar bom dia execute resumo do dia") == ("bom dia", "resumo do dia")
    assert ler_ensino("quando eu falar com o João") is None
    assert ler_ensino("quando eu falar com o João, me lembre de cobrar") is None
    t = {"painel das cameras": "abrir planta das cameras"}
    assert traduzir_ensinado("painel das cameras", t) == "abrir planta das cameras"
    assert traduzir_ensinado("abra o painel das cameras por favor", t) == "abrir planta das cameras"
    assert traduzir_ensinado("abre o painel da camera", t) == "abrir planta das cameras"
    assert traduzir_ensinado("abra o painel de energia", t) is None


def test_catalogo_entende_jeitos_diferentes():
    from ghost.automacao.automacoes import resolver_catalogo
    assert resolver_catalogo("Painel das Câmeras") == ("abrir planta das cameras", True)
    assert resolver_catalogo("abrir modelo 3D das câmeras") == ("abrir planta das cameras", True)
    assert resolver_catalogo("Câmera", aproximado=False) is None               # app Câmera do Windows
    assert resolver_catalogo("mapa da rede")[0] == "mostrar o link neural da rede"
    assert resolver_catalogo("exportar os indicadores")[0] == "exportar indicadores"
    assert resolver_catalogo("Excel") is None
