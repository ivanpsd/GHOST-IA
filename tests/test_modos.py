"""Modos da ativação: normal / conversa ("oi Ghost") / dormindo ("tchau Ghost")."""
import time

from tests.conftest import windows

pytestmark = windows


def test_definir_modo():
    from ghost.voz import ativacao
    try:
        ativacao.definir_modo("conversa")
        assert ativacao.modo() == "conversa" and ativacao._conversa_ate > time.time()
        ativacao.definir_modo("dormindo")
        ativacao.aguardar_comando(5)                 # dormindo: não abre a janela de resposta
        assert ativacao._aguardando_ate == 0.0
    finally:
        ativacao.definir_modo("normal")
    assert ativacao.modo() == "normal"
