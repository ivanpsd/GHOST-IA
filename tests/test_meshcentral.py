"""Máquinas do MeshCentral (somente leitura): resumo, alertas e junção com o inventário da rede."""
from ghost.servicos import meshcentral as mc

GUSTAVO = {"name": "Ti_Gustavo", "ip": "192.168.50.7", "conn": 1, "users": ["TI_GUSTAVO\\gusta"],
           "lastbootuptime": 1792148496000, "osdesc": "Windows 11 Home", "idletime": 12,
           "av": [{"product": "Windows Defender", "updated": True, "enabled": True}],
           "wsc": {"antiVirus": "OK", "autoUpdate": "OK", "firewall": "OK"}, "pr": []}
IVAN = {"name": "Ti-Ivan", "ip": "192.168.50.37", "conn": 1, "users": ["TI-IVAN\\TI-Ivan"],
        "av": [{"product": "Windows Defender", "updated": True, "enabled": True}],
        "wsc": {"antiVirus": "OK", "autoUpdate": "OK", "firewall": "WARNING"}, "pr": ["File Rename"]}
INV = {"m": {"ip": "192.168.50.7", "apelido": "PC do Gustavo", "responsavel": "Gustavo", "departamento": "TI"}}


def test_resumo_e_problemas():
    r = mc.resumo(IVAN)
    assert r["usuarios"] == ["TI-Ivan"] and r["ligado"] and not r["firewall_ok"]
    assert mc.problemas(r) == ["firewall com alerta", "reinício pendente"]
    assert mc.problemas(mc.resumo(GUSTAVO)) == []


def test_texto_procura_alertas_e_sem_tempo_de_inatividade():
    t = mc.texto([GUSTAVO, IVAN], INV, "procurar", "gustavo")
    assert "PC do Gustavo (Gustavo, TI)" in t and "logado: gusta" in t and "segurança em ordem" in t
    assert "inativ" not in t.lower()                                 # tempo ocioso da pessoa não é informado
    a = mc.texto([GUSTAVO, IVAN], INV, "alertas")
    assert "Ti-Ivan: firewall com alerta, reinício pendente" in a and "Gustavo" not in a
    assert "Nenhuma máquina" in mc.texto([GUSTAVO], INV, "procurar", "paula")


def test_sem_configuracao(monkeypatch):
    for k in ("MESH_URL", "MESH_USUARIO", "MESH_SENHA"):
        monkeypatch.delenv(k, raising=False)
    mc._cache.update(t=0, dados=None, erro=None)
    assert "não está configurado" in mc.consultar()
