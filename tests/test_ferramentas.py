"""Proteção: depois de ler algo de fora (e-mail, tela...), as ações só rodam com confirmação."""
from tests.conftest import windows

pytestmark = windows


def test_todas_as_ferramentas_estao_classificadas():
    from ghost.ia import ferramentas
    nomes = {t["function"]["name"] if "function" in t else t["name"] for t in ferramentas.TOOLS}
    assert not (ferramentas.EXTERNAS & ferramentas.ACOES)
    assert (ferramentas.EXTERNAS | ferramentas.ACOES) <= nomes | {"consultar_sistema"}
    # ferramentas que mexem no PC ou mandam algo precisam estar em ACOES
    for n in ("abrir_aplicativo", "digitar_texto", "pressionar_teclas", "comando_ghost", "controlar_casa",
              "tarefa_segundo_plano", "configurar_notificacoes"):
        assert n in ferramentas.ACOES
    for n in ("consultar_emails", "olhar_tela", "listar_notificacoes", "ver_planilha"):
        assert n in ferramentas.EXTERNAS


def test_args_json_sempre_dicionario():
    from ghost.ia import ferramentas
    assert ferramentas.args_json('{"a": 1}') == {"a": 1}
    assert ferramentas.args_json("[1, 2]") == {}
    assert ferramentas.args_json("não é json") == {}
    assert ferramentas.args_json(None) == {}
