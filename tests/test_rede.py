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


def test_ip_exato_nao_pega_vizinhos():
    inv = {"a": {"ip": "192.168.50.1", "mac": "a"}, "b": {"ip": "192.168.50.10", "mac": "b"}}
    assert [x["mac"] for x in rede.procurar(inv, "192.168.50.1")] == ["a"]


def test_alerta_so_depois_de_2_falhas_e_aviso_de_volta():
    from ghost.servicos import monitor_rede as mon
    e = {}
    assert mon.registrar_teste("srv", False, 0, e) == (None, None)          # 1 falha: ainda não avisa
    assert mon.registrar_teste("srv", False, 60, e) == ("caiu", None)
    assert mon.registrar_teste("srv", False, 120, e) == (None, None)        # não repete
    assert mon.registrar_teste("srv", True, 300, e) == ("voltou", 5)
    assert mon.registrar_teste("srv", False, 360, e) == (None, None)        # oscilou 1 vez: sem alarme
    assert mon.registrar_teste("srv", True, 420, e) == (None, None)


def test_historico_da_internet_separa_provedor_de_rede_interna():
    from ghost.servicos import monitor_rede as mon
    linhas = [{"t": 0, "gw_ms": 1, "net_ms": 5}, {"t": 60, "gw_ms": 1, "net_ms": None}, {"t": 120, "gw_ms": 1, "net_ms": None},
              {"t": 180, "gw_ms": 1, "net_ms": 7}, {"t": 240, "gw_ms": None, "net_ms": None}, {"t": 300, "gw_ms": 2, "net_ms": 6}]
    r = mon.resumir_internet(linhas, 0, 300)
    assert r["disponibilidade"] == 50.0 and r["latencia_media"] == 6 and r["latencia_max"] == 7
    assert [(q["min"], q["causa"]) for q in r["quedas"]] == [(2, "provedor de internet"), (1, "rede interna/roteador")]


def test_exportar_excel(monkeypatch, tmp_path):
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from ghost.nucleo import arquivo
    from ghost.servicos import monitor_rede as mon
    monkeypatch.setattr(rede, "ARQUIVO", str(tmp_path / "rede.json"))
    monkeypatch.setattr(rede, "PASTA_EXPORTAR", str(tmp_path / "rel"))
    monkeypatch.setattr(mon, "ARQ_INTERNET", str(tmp_path / "internet.jsonl"))
    monkeypatch.setattr(mon, "ARQ_EVENTOS", str(tmp_path / "eventos.jsonl"))
    rede._salvar({"m1": {"mac": "m1", "ip": "192.168.50.120", "nome": "SERVIDOR-SADIN", "critico": True,
                         "primeira_vez": 1, "ultima_vez": 2}})
    arquivo.acrescentar_jsonl(mon.ARQ_INTERNET, {"t": 1_800_000_000, "gw_ms": 1, "net_ms": 5})
    arquivo.acrescentar_jsonl(mon.ARQ_EVENTOS, {"t": 1_800_000_000, "nome": "SERVIDOR-SADIN", "tipo": "caiu", "min": None})
    wb = openpyxl.load_workbook(rede.exportar())
    assert wb.sheetnames == ["Inventário", "Quedas", "Internet por dia"]
    assert wb["Inventário"]["D2"].value == "SERVIDOR-SADIN" and wb["Inventário"]["H2"].value == "sim"
    assert wb["Internet por dia"]["B2"].value == 100.0


def test_tipo_de_aparelho_para_o_mapa():
    from ghost.nucleo import huds
    t = lambda nome, ip="192.168.50.9": huds.tipo_aparelho({"nome": nome, "ip": ip}, "192.168.50.1")  # noqa: E731
    assert t("x", "192.168.50.1") == "roteador" and t("SERVIDOR-SADIN") == "servidor"
    assert t("IMP_FIN") == "impressora" and t("NPI3328AD") == "impressora" and t("SEC8425196B52B5") == "impressora"
    assert t("ADM-PAULA") == "computador" and t(None) == "desconhecido"


def test_hud_da_rede_servido_com_a_chave(monkeypatch, tmp_path):
    import json
    import urllib.request

    from ghost.nucleo import huds, painel
    monkeypatch.setattr(huds, "DADOS", {"rede": lambda: {"aparelhos": [], "internet": {}, "gerado": 1}})
    painel.iniciar(abrir=False)
    base = f"http://127.0.0.1:{painel._servidor.server_address[1]}"
    html = urllib.request.urlopen(f"{base}/hud/rede?t={painel._token}").read().decode()
    assert "LINK NEURAL" in html and painel._token in html and "__GHOST_TOKEN__" not in html
    assert json.loads(urllib.request.urlopen(f"{base}/hud/rede/dados?t={painel._token}").read())["gerado"] == 1
    import urllib.error
    try:
        urllib.request.urlopen(f"{base}/hud/rede/dados?t=errada")
        raise AssertionError("deveria negar")
    except urllib.error.HTTPError as e:
        assert e.code == 403


def test_departamentos_e_edicao_pela_tela(monkeypatch, tmp_path):
    monkeypatch.setattr(rede, "ARQUIVO", str(tmp_path / "rede.json"))
    monkeypatch.setattr(rede, "ARQ_DEPARTAMENTOS", str(tmp_path / "deps.json"))
    rede._salvar({"m1": {"mac": "m1", "ip": "192.168.50.13", "nome": "SEC8425196B52B5"},
                  "m2": {"mac": "m2", "ip": "192.168.50.18", "nome": "ADM-PAULA"}})
    assert rede.definir_departamentos(["TI", "Financeiro", "Comercial", "RH", "Produção", "rh"]) == \
        ["TI", "Financeiro", "Comercial", "RH", "Produção"]                       # "rh" repetido não duplica
    feitos, nao, amb = rede.atribuir_departamento(["192.168.50.18", "192.168.50.99"], "Financeiro")
    assert feitos == ["ADM-PAULA"] and nao == ["192.168.50.99"] and amb == []
    a = rede.editar("m1", {"apelido": "Impressora Financeiro", "departamento": "Administrativo", "critico": False})
    assert a["apelido"] == "Impressora Financeiro" and a["critico"] is False
    assert "Administrativo" in rede.departamentos()                               # criado ao usar
    assert "responsavel" not in rede.editar("m1", {"responsavel": ""})            # vazio apaga
    assert rede.definir_departamentos(["Produção"], remover=True).count("Produção") == 0
    assert rede.editar("nao-existe", {"apelido": "x"}) is None


def test_frase_de_departamento_nao_reabre_o_mapa(monkeypatch):
    import pytest
    pytest.importorskip("pyautogui")
    from ghost.automacao import automacoes as a
    from ghost.nucleo import painel
    abertos = []
    monkeypatch.setattr(painel, "abrir_hud", lambda nome: abertos.append(nome) or True)
    assert a._tratar_hud(a.normalizar("mostre o link neural da rede"), lambda t: None) is True
    assert abertos == ["rede"]
    for frase in ("Consegue criar quatro departamentos no link neural? RH, financeiro, comercial e produção",
                  "no link neural coloque a impressora no financeiro"):
        assert a._tratar_hud(a.normalizar(frase), lambda t: None) is not True
    assert abertos == ["rede"]
