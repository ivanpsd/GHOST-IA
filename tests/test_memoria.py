

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
