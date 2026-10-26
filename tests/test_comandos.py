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


@pytest.mark.parametrize("frase", ["oi ghost", "olá, Ghost!", "ei ghost tudo bem", "ghost, vamos conversar", "Ghost acorda"])
def test_frases_que_ligam_a_conversa(app, auto, frase):
    assert app.FRASE_CONVERSA.fullmatch(auto.normalizar(frase))


@pytest.mark.parametrize("frase", ["tchau ghost", "boa noite, Ghost", "Ghost, pode descansar", "até amanhã ghost valeu"])
def test_frases_que_fazem_dormir(app, auto, frase):
    assert app.FRASE_DORMIR.fullmatch(auto.normalizar(frase))


@pytest.mark.parametrize("frase", ["oi ghost abre o excel", "boa noite pessoal da reunião", "ghost qual a previsão do tempo",
                                   "tchau tchau para o problema"])
def test_frases_comuns_nao_mudam_o_modo(app, auto, frase):
    n = auto.normalizar(frase)
    assert not app.FRASE_CONVERSA.fullmatch(n) and not app.FRASE_DORMIR.fullmatch(n)


@pytest.mark.parametrize("frase", ["Precisa de mais alguma coisa, senhor?", "Posso ajudar em algo mais?",
                                   "Mais alguma coisa?", "Senhor, deseja mais algum detalhe?"])
def test_oferta_generica_e_cortada(app, frase):
    assert app._oferta_generica(frase)


@pytest.mark.parametrize("frase", ["Quer que eu abra a planilha de produção?", "Para qual contato envio, senhor?",
                                   "A reunião é às 14h ou às 15h?"])
def test_pergunta_util_passa(app, frase):
    assert not app._oferta_generica(frase)


def test_nome_no_inicio(app):
    assert app.NOME_NO_INICIO.match("Ghost, que horas são")
    assert app.NOME_NO_INICIO.match("ei ghost abre o excel")
    assert not app.NOME_NO_INICIO.match("o fantasma da ópera")


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
