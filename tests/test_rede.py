"""Rede (somente leitura): leitura do ARP e do NetBIOS, inventário, procura e apelidos."""
from ghost.servicos import rede

ARP = """
Interface: 192.168.50.37 --- 0x9
  Endereço IP           Endereço físico       Tipo
  192.168.50.1          18-fd-74-ac-ab-15     dinâmico
  192.168.50.7          5c-53-10-4d-4c-2e     dinâmico
  192.168.50.255        ff-ff-ff-ff-ff-ff     estático
  224.0.0.22            01-00-5e-00-00-16     estático
  192.168.50.40         5c:53:10:aa:bb:cc     dynamic
"""

NBT = """
           Tabela de nomes NetBIOS da máquina remota
       Nome               Tipo         Status
    ---------------------------------------------
    TI_GUSTAVO     <00>  EXCLUSIVO   Registrado
    TI             <00>  GRUPO       Registrado
    TI_GUSTAVO     <20>  EXCLUSIVO   Registrado
"""


def test_arp_e_nbtstat():
    t = rede.ler_arp(ARP)
    assert t == {"192.168.50.1": "18-fd-74-ac-ab-15", "192.168.50.7": "5c-53-10-4d-4c-2e",
                 "192.168.50.40": "5c-53-10-aa-bb-cc"}
    assert rede.ler_nbtstat(NBT) == ("TI_GUSTAVO", "TI")
    assert rede.ler_nbtstat("Host não encontrado.") == (None, None)


def test_mac_aleatorio_de_celular():
    assert rede.mac_aleatorio("da-a1-19-00-00-01") and not rede.mac_aleatorio("5c-53-10-4d-4c-2e")


def test_inventario_novos_procura_e_apelido(monkeypatch, tmp_path):
    monkeypatch.setattr(rede, "ARQUIVO", str(tmp_path / "rede.json"))
    inv = {}
    novos = rede.mesclar(inv, {"5c-53-10-4d-4c-2e": {"ip": "192.168.50.7", "nome": "TI_GUSTAVO"}}, agora=1000)
    assert novos == ["5c-53-10-4d-4c-2e"]
    assert rede.mesclar(inv, {"5c-53-10-4d-4c-2e": {"ip": "192.168.50.8", "nome": None}}, agora=2000) == []
    a = inv["5c-53-10-4d-4c-2e"]
    assert a["ip"] == "192.168.50.8" and a["nome"] == "TI_GUSTAVO" and a["primeira_vez"] == 1000   # nome não some
    rede._salvar(inv)
    feito, n = rede.nomear("192.168.50.8", apelido="PC do Gustavo", responsavel="Gustavo", departamento="TI")
    assert n == 1 and feito["responsavel"] == "Gustavo"
    assert rede.procurar(rede.carregar(), "gustavo")[0]["apelido"] == "PC do Gustavo"
    assert rede.nomear("nao-existe")[0] is None
    assert rede.online(a, agora=2000 + 60) and not rede.online(a, agora=2000 + rede.ONLINE_S + 1)
