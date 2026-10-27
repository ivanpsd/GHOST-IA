"""Ativação só pelo F9: modos normal / dormindo ("tchau Ghost" = não perturbe)."""
from tests.conftest import windows

pytestmark = windows


def test_definir_modo():
    from ghost.voz import ativacao
    try:
        ativacao.definir_modo("conversa")            # modo conversa não existe mais: vira normal
        assert ativacao.modo() == "normal"
        ativacao.definir_modo("dormindo")
        assert ativacao.modo() == "dormindo" and not ativacao.janela_aberta()
    finally:
        ativacao.definir_modo("normal")
    assert ativacao.modo() == "normal" and ativacao.segundos_sem_voz() == float("inf")
