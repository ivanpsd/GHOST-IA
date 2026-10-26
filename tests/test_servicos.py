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


def test_resumo_fala_eventos_do_dia_todo():
    from datetime import date

    from ghost.servicos import resumo
    itens = [(date(2026, 10, 23), None, "Feriado", ""), (date(2026, 10, 23), "09:00", "Reunião", "")]
    assert resumo._falar_eventos(itens) == "Feriado (o dia todo); Reunião às 09:00"
