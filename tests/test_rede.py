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
    e = {}
    assert rede.registrar_teste("srv", False, 0, e) == (None, None)          # 1 falha: ainda não avisa
    assert rede.registrar_teste("srv", False, 60, e) == ("caiu", None)
    assert rede.registrar_teste("srv", False, 120, e) == (None, None)        # não repete
    assert rede.registrar_teste("srv", True, 300, e) == ("voltou", 5)
    assert rede.registrar_teste("srv", False, 360, e) == (None, None)        # oscilou 1 vez: sem alarme
    assert rede.registrar_teste("srv", True, 420, e) == (None, None)


def test_historico_da_internet_separa_provedor_de_rede_interna():
    linhas = [{"t": 0, "gw_ms": 1, "net_ms": 5}, {"t": 60, "gw_ms": 1, "net_ms": None}, {"t": 120, "gw_ms": 1, "net_ms": None},
              {"t": 180, "gw_ms": 1, "net_ms": 7}, {"t": 240, "gw_ms": None, "net_ms": None}, {"t": 300, "gw_ms": 2, "net_ms": 6}]
    r = rede.resumir_internet(linhas, 0, 300)
    assert r["disponibilidade"] == 50.0 and r["latencia_media"] == 6 and r["latencia_max"] == 7
    assert [(q["min"], q["causa"]) for q in r["quedas"]] == [(2, "provedor de internet"), (1, "rede interna/roteador")]


def test_exportar_excel(monkeypatch, tmp_path):
    import pytest
    openpyxl = pytest.importorskip("openpyxl")
    from ghost.nucleo import arquivo
    monkeypatch.setattr(rede, "ARQUIVO", str(tmp_path / "rede.json"))
    monkeypatch.setattr(rede, "PASTA_EXPORTAR", str(tmp_path / "rel"))
    monkeypatch.setattr(rede, "ARQ_INTERNET", str(tmp_path / "internet.jsonl"))
    monkeypatch.setattr(rede, "ARQ_EVENTOS", str(tmp_path / "eventos.jsonl"))
    rede._salvar({"m1": {"mac": "m1", "ip": "192.168.50.120", "nome": "SERVIDOR-SADIN", "critico": True,
                         "primeira_vez": 1, "ultima_vez": 2}})
    arquivo.acrescentar_jsonl(rede.ARQ_INTERNET, {"t": 1_800_000_000, "gw_ms": 1, "net_ms": 5})
    arquivo.acrescentar_jsonl(rede.ARQ_EVENTOS, {"t": 1_800_000_000, "nome": "SERVIDOR-SADIN", "tipo": "caiu", "min": None})
    wb = openpyxl.load_workbook(rede.exportar())
    assert wb.sheetnames == ["Inventário", "Quedas", "Internet por dia"]
    assert wb["Inventário"]["D2"].value == "SERVIDOR-SADIN" and wb["Inventário"]["H2"].value == "sim"
    assert wb["Internet por dia"]["B2"].value == 100.0


def test_tipo_de_aparelho_para_o_mapa():
    t = lambda nome, ip="192.168.50.9": rede.tipo_aparelho({"nome": nome, "ip": ip}, "192.168.50.1")  # noqa: E731
    assert t("x", "192.168.50.1") == "roteador" and t("SERVIDOR-SADIN") == "servidor"
    assert t("IMP_FIN") == "impressora" and t("NPI3328AD") == "impressora" and t("SEC8425196B52B5") == "impressora"
    assert t("ADM-PAULA") == "computador" and t(None) == "desconhecido"


def test_hud_da_rede_servido_com_a_chave(monkeypatch, tmp_path):
    import json
    import urllib.request

    from ghost.nucleo import painel
    monkeypatch.setitem(painel.HUDS, "rede", ("Link neural da rede", lambda: {"aparelhos": [], "internet": {}, "gerado": 1}))
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


# ---------------- agentes MeshCentral
GUSTAVO = {"name": "Ti_Gustavo", "ip": "192.168.50.7", "conn": 1, "users": ["TI_GUSTAVO\\gusta"],
           "lastbootuptime": 1792148496000, "osdesc": "Windows 11 Home", "idletime": 12,
           "av": [{"product": "Windows Defender", "updated": True, "enabled": True}],
           "wsc": {"antiVirus": "OK", "autoUpdate": "OK", "firewall": "OK"}, "pr": []}
IVAN = {"name": "Ti-Ivan", "ip": "192.168.50.37", "conn": 1, "users": ["TI-IVAN\\TI-Ivan"],
        "av": [{"product": "Windows Defender", "updated": True, "enabled": True}],
        "wsc": {"antiVirus": "OK", "autoUpdate": "OK", "firewall": "WARNING"}, "pr": ["File Rename"]}
INV = {"m": {"ip": "192.168.50.7", "apelido": "PC do Gustavo", "responsavel": "Gustavo", "departamento": "TI"}}


def test_resumo_e_problemas():
    r = rede.resumo_agente(IVAN)
    assert r["usuarios"] == ["TI-Ivan"] and r["ligado"] and not r["firewall_ok"]
    assert rede.problemas_agente(r) == ["firewall com alerta", "reinício pendente"]
    assert rede.problemas_agente(rede.resumo_agente(GUSTAVO)) == []


def test_texto_procura_alertas_e_sem_tempo_de_inatividade():
    t = rede.texto_agentes([GUSTAVO, IVAN], INV, "procurar", "gustavo")
    assert "PC do Gustavo (Gustavo, TI)" in t and "logado: gusta" in t and "segurança em ordem" in t
    assert "inativ" not in t.lower()                                 # tempo ocioso da pessoa não é informado
    a = rede.texto_agentes([GUSTAVO, IVAN], INV, "alertas")
    assert "Ti-Ivan: firewall com alerta, reinício pendente" in a and "Gustavo" not in a
    assert "Nenhuma máquina" in rede.texto_agentes([GUSTAVO], INV, "procurar", "paula")


def test_sem_configuracao(monkeypatch):
    for k in ("MESH_URL", "MESH_USUARIO", "MESH_SENHA"):
        monkeypatch.delenv(k, raising=False)
    rede._cache_mesh.update(t=0, dados=None, erro=None)
    assert "não está configurado" in rede.consultar_agentes()


# ---------------- ações manuais e impressoras
def test_pacote_wake_on_lan():
    p = rede.pacote_wol("5c-53-10-4d-4c-2e")
    assert len(p) == 102 and p[:6] == b"\xff" * 6 and p[6:12] == bytes.fromhex("5c53104d4c2e")
    import pytest
    with pytest.raises(ValueError):
        rede.pacote_wol("xx")


def test_acao_manual_so_lista_fechada(monkeypatch, tmp_path):
    import pytest
    monkeypatch.setattr(rede, "ARQUIVO", str(tmp_path / "rede.json"))
    rede._salvar({"m1": {"mac": "m1", "ip": "192.168.50.7"}})
    with pytest.raises(ValueError, match="não permitida"):
        rede.acao_manual("m1", "formatar")
    with pytest.raises(ValueError, match="inventário"):
        rede.acao_manual("nao-existe", "ligar")
    with pytest.raises(ValueError, match="vazia"):
        rede.acao_manual("m1", "mensagem", "  ")


def test_snmp_ida_e_volta():
    pedido = rede.snmp_pedido("1.3.6.1.2.1.43.11.1.1.9.1", proximo=True)
    assert pedido[0] == 0x30 and b"public" in pedido and bytes([0xA1]) in pedido
    # resposta fabricada: GetResponse com o nível 1234 no OID 1.3.6.1.2.1.43.11.1.1.9.1.1
    vb = rede._ber(0x30, rede._ber(0x30, rede._ber_oid("1.3.6.1.2.1.43.11.1.1.9.1.1") + rede._ber_int(1234)))
    pdu = rede._ber(0xA2, rede._ber_int(1) + rede._ber_int(0) + rede._ber_int(0) + vb)
    resp = rede._ber(0x30, rede._ber_int(0) + rede._ber(0x04, b"public") + pdu)
    assert rede.snmp_resposta(resp) == ("1.3.6.1.2.1.43.11.1.1.9.1.1", 1234)


def test_erros_e_nivel_da_impressora():
    assert rede.erros_impressora(bytes([0b00110000, 0b00000100])) == ["pouco toner", "sem toner", "bandeja vazia"]
    assert rede.nivel_pct(380, 1000) == "38%" and rede.nivel_pct(-3, -2) == "tem (sem medida)"


def test_agente_casa_pelo_nome_mesmo_com_ip_ipv6():
    inv = {"aa": {"mac": "aa", "ip": "192.168.50.7", "nome": "TI_GUSTAVO"},
           "bb": {"mac": "bb", "ip": "192.168.50.37", "nome": "TI-IVAN"}}
    assert rede.aparelho_do_agente({"nome": "Ti_Gustavo", "ip": "fe80::1%9"}, inv)["mac"] == "aa"
    assert rede.aparelho_do_agente({"nome": "Ti-Ivan", "ip": "192.168.50.37"}, inv)["mac"] == "bb"
    assert rede.aparelho_do_agente({"nome": "Outro", "ip": "192.168.50.37"}, inv)["mac"] == "bb"   # cai no IP
    assert rede.aparelho_do_agente({"nome": "Outro", "ip": "10.0.0.1"}, inv) is None


def test_evento_do_gravador():
    assert rede.ler_evento_cam("Code=VideoMotion;action=Start;index=12;data={") == ("movimento", "Start", 13)
    assert rede.ler_evento_cam("Code=SmartMotionHuman;action=Stop;index=0") == ("pessoa", "Stop", 1)
    assert rede.ler_evento_cam("Heartbeat") is None
    assert rede.ler_evento_cam("Code=VideoLoss;action=Start;index=0") is None


def test_canal_acende_e_apaga_depois_do_stop():
    canais = {}
    rede.aplicar_evento_cam(canais, ("movimento", "Start", 3), 100)
    assert rede.situacao_canal(canais[3], 101) == "movimento"
    rede.aplicar_evento_cam(canais, ("pessoa", "Start", 3), 102)
    assert rede.situacao_canal(canais[3], 103) == "pessoa"          # pessoa vence movimento
    rede.aplicar_evento_cam(canais, ("pessoa", "Stop", 3), 104)
    rede.aplicar_evento_cam(canais, ("movimento", "Stop", 3), 104)
    assert rede.situacao_canal(canais[3], 104 + rede.CAM_ACESO_S) == "pessoa"
    assert rede.situacao_canal(canais[3], 105 + rede.CAM_ACESO_S) is None


def test_cameras_da_planta_validadas():
    r = rede.validar_cameras([{"canal": "2", "x": 10.4, "y": 20, "ang": 370, "nome": " Corredor "},
                              {"canal": 99, "x": 0, "y": 0}, {"canal": 2, "x": 30, "y": 40}, {"x": 1}, "lixo"])
    assert r == [{"canal": 2, "x": 30, "y": 40, "ang": 0, "nome": "", "sala": ""}]
    assert rede.validar_cameras([{"canal": 1, "x": 0, "y": 0, "sala": "rh<script>"}])[0]["sala"] == "rhscript"
    assert rede.validar_cameras(None) == []
    assert {s["id"] for s in rede.PLANTA_PADRAO["salas"]} >= {"almox", "rh", "financeiro", "servidor"}


def test_planta_alinhada_na_grade():
    p = rede.PLANTA_PADRAO
    for s in p["salas"] + p["moveis"]:
        assert all(s[k] % 10 == 0 for k in ("x", "y", "w", "h")), s["nome"]
    assert "cameras" not in p                                  # câmeras ficam só em dados/cameras.json
