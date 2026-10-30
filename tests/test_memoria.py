

def test_memoria_longa_busca_por_palavras(monkeypatch, tmp_path):
    """Busca leve (sem modelo): acha pela palavra mesmo no plural/sem acento e ignora o que não tem a ver."""
    from ghost.ia import memoria_longa as ml
    monkeypatch.setattr(ml, "ARQ_TEXTO", str(tmp_path / "hist.jsonl"))
    monkeypatch.setattr(ml, "_itens", None)
    ml.adicionar("o fornecedor de embalagens atrasou", "Anotado, senhor.", quando=1_800_000_000)
    ml.adicionar("qual a previsão do tempo amanhã", "Sol, 28 graus.", quando=1_800_000_100)
    ml.adicionar("quanto produzimos ontem", "1.200 unidades.", quando=1_800_000_200)
    r = ml.buscar("Fornecedores de EMBALAGEM")
    assert "fornecedor de embalagens" in r and "previsão" not in r
    assert "Não encontrei" in ml.buscar("contrato de aluguel")
    assert ml.pontuar("", [{}]) == [0.0]


def test_memoria_so_fatos_relevantes_e_aprende_so_quando_vale():
    from ghost.ia import memoria
    fatos = [{"texto": f"fato genérico número {i}"} for i in range(40)] + [{"texto": "Usuário cuida do PCP da fábrica"}]
    escolhidos = memoria.escolher_fatos(fatos, "como está o PCP hoje?")
    assert len(escolhidos) == memoria.FATOS_NO_PROMPT
    assert any("PCP" in f["texto"] for f in escolhidos)
    assert not memoria.vale_aprender("obrigado")
    assert not memoria.vale_aprender("abra o painel das câmeras")
    assert memoria.vale_aprender("eu prefiro que você me chame de Ivan sempre")
