"""Central de avisos: espera silêncio, prioridade, junta avisos e descarta os velhos."""
import pytest

from ghost.nucleo import avisos


@pytest.fixture(autouse=True)
def fila_limpa():
    avisos._fila.clear()
    yield
    avisos._fila.clear()


def test_espera_silencio_e_fala_quando_livre():
    avisos.anunciar("Senhor, WhatsApp: Leonard.")
    ocupado = lambda s: False  # noqa: E731
    falando = lambda: False  # noqa: E731
    assert avisos.escolher(avisos._fila[0]["t"] + 10, ocupado, falando) == ([], [])     # sala com conversa: espera
    silencio = []
    falar, _ = avisos.escolher(avisos._fila[0]["t"] + 10, lambda s: silencio.append(s) or True, falando)
    assert [a["texto"] for a in falar] == ["Senhor, WhatsApp: Leonard."] and silencio == [6.0]


def test_critico_primeiro_juntos_numa_frase():
    avisos.anunciar("Senhor, WhatsApp: Leonard.")
    avisos.anunciar("Senhor, o SERVIDOR-SADIN caiu.", "critica")
    falar, _ = avisos.escolher(avisos._fila[0]["t"] + 1, lambda s: True, lambda: False)
    assert avisos._juntar(falar) == "Senhor, 2 avisos. O SERVIDOR-SADIN caiu. WhatsApp: Leonard."


def test_critico_fala_mesmo_sem_silencio_depois_de_esperar_e_comum_vence():
    avisos.anunciar("Senhor, apareceu um aparelho novo na rede.")
    avisos.anunciar("Senhor, a internet caiu.", "critica")
    t0 = max(a["t"] for a in avisos._fila)
    falar, vencidos = avisos.escolher(t0 + 400, lambda s: False, lambda: False)
    assert [a["texto"] for a in falar] == ["Senhor, a internet caiu."]               # esperou 90 s: fala
    assert [a["texto"] for a in vencidos] == ["Senhor, apareceu um aparelho novo na rede."]   # 5 min: descartado
    assert avisos.escolher(t0 + 400, lambda s: True, lambda: False) == ([], [])


def test_mesma_chave_substitui():
    avisos.anunciar("internet caiu", "critica", chave="internet")
    avisos.anunciar("internet voltou", "critica", chave="internet")
    assert [a["texto"] for a in avisos._fila] == ["internet voltou"]
