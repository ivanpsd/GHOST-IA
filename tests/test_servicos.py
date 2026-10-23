import pytest

from tests.conftest import windows


@windows
@pytest.mark.parametrize("app_id,nome", [
    ("5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "WhatsApp"),
    ("Microsoft.Office.OUTLOOK.EXE.15", "Outlook"),
    ("MSTeams_8wekyb3d8bbwe!MSTeams", "Teams"),
    ("Contoso.MeuApp_abcdef123456!App", "MeuApp"),
])
def test_nome_do_app_da_notificacao(app_id, nome):
    from ghost.servicos import notificacoes
    assert notificacoes._nome_app(app_id) == nome


def test_erro_do_telegram_nao_mostra_o_token(monkeypatch):
    from ghost.servicos import telegram_bot
    monkeypatch.setenv("TELEGRAM_TOKEN", "123:SEGREDO")
    erro = RuntimeError("HTTPSConnectionPool: /bot123:SEGREDO/getUpdates falhou")
    assert "SEGREDO" not in telegram_bot._limpo(erro)


def test_telegram_dono(monkeypatch):
    from ghost.servicos import telegram_bot
    monkeypatch.setenv("TELEGRAM_TOKEN", "1:x")
    monkeypatch.setenv("TELEGRAM_DONO", "123456789")
    assert telegram_bot._dono() == 123456789 and telegram_bot.configurado()
    monkeypatch.setenv("TELEGRAM_DONO", "abc")
    assert telegram_bot._dono() is None and not telegram_bot.configurado()


def test_resumo_fala_eventos_do_dia_todo():
    from datetime import date

    from ghost.servicos import resumo
    itens = [(date(2026, 10, 23), None, "Feriado", ""), (date(2026, 10, 23), "09:00", "Reunião", "")]
    assert resumo._falar_eventos(itens) == "Feriado (o dia todo); Reunião às 09:00"
