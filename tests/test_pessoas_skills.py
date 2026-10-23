import pytest

from ghost.ia import pessoas, skills
from ghost.nucleo import arquivo


@pytest.fixture
def fichas(tmp_path, monkeypatch):
    arq = str(tmp_path / "pessoas.json")
    monkeypatch.setattr(pessoas, "ARQUIVO", arq)
    arquivo.salvar_json(arq, [
        {"nome": "Deborah Souza", "funcao": "minha lider", "apelidos": ["Deb"]},
        {"nome": "Gustavo Silva", "funcao": "", "apelidos": []},
        {"nome": "Gustavo Lima", "funcao": "", "apelidos": []},
    ])


def test_busca_por_primeiro_nome_unico(fichas):
    assert pessoas.buscar("Deborah")["nome"] == "Deborah Souza"
    assert pessoas.buscar("deb")["nome"] == "Deborah Souza"


def test_primeiro_nome_ambiguo_nao_chuta(fichas):
    assert pessoas.buscar("Gustavo") is None
    assert pessoas.buscar("Gustavo Pereira") is None


def test_resolver_contato_so_com_uma_ficha(fichas):
    assert pessoas.resolver_contato("minha líder") == "Deborah Souza"
    assert pessoas.resolver_contato("Gustavo") == "Gustavo"


@pytest.fixture
def lista_skills(tmp_path, monkeypatch):
    arq = str(tmp_path / "skills.json")
    monkeypatch.setattr(skills, "ARQUIVO", arq)
    arquivo.salvar_json(arq, [
        {"nome": "relatorio", "gatilhos": ["relatório"], "passos": []},
        {"nome": "abrir producao", "gatilhos": ["abrir rotina de produção"], "passos": []},
        {"nome": "relatorio semanal", "gatilhos": ["relatório semanal"], "passos": []},
    ])


def test_gatilho_curto_so_vale_exato(lista_skills):
    assert skills.encontrar("relatorio")["nome"] == "relatorio"
    assert skills.encontrar("qual o valor do relatorio de ontem") is None


def test_gatilho_longo_vale_dentro_da_frase(lista_skills):
    assert skills.encontrar("ghost por favor abrir rotina de producao agora")["nome"] == "abrir producao"


def test_excluir_exato_apaga_so_ele(lista_skills):
    assert skills.excluir("relatorio") == 1
    assert [s["nome"] for s in skills.carregar()] == ["abrir producao", "relatorio semanal"]


def test_excluir_ambiguo_nao_apaga(lista_skills):
    skills.salvar({"nome": "relatorio mensal", "gatilhos": ["relatório mensal"], "passos": []})
    skills.excluir("relatorio")
    assert sorted(skills.excluir("relat")) == ["relatorio mensal", "relatorio semanal"]
    assert len(skills.carregar()) == 3
    assert skills.excluir("inexistente") == 0


def test_arquivo_corrompido_nao_e_sobrescrito(tmp_path, monkeypatch):
    arq = tmp_path / "skills.json"
    arq.write_text("{quebrado", encoding="utf-8")
    monkeypatch.setattr(skills, "ARQUIVO", str(arq))
    assert skills.carregar() == []
    with pytest.raises(arquivo.ArquivoCorrompido):
        skills.salvar({"nome": "x", "gatilhos": ["x"], "passos": []})
    assert arq.read_text(encoding="utf-8") == "{quebrado"
