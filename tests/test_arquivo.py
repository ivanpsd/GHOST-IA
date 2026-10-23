import json
import os

import pytest

from ghost.nucleo import arquivo


def test_salvar_e_ler_json(tmp_path):
    p = str(tmp_path / "sub" / "a.json")
    arquivo.salvar_json(p, {"x": "ação", "n": [1, 2]})
    assert arquivo.ler_json(p) == {"x": "ação", "n": [1, 2]}
    assert not [f for f in os.listdir(tmp_path / "sub") if f.endswith(".tmp")]


def test_ler_json_inexistente_devolve_padrao(tmp_path):
    assert arquivo.ler_json(str(tmp_path / "nada.json"), []) == []


def test_ler_json_corrompido_guarda_copia_e_avisa(tmp_path):
    p = tmp_path / "c.json"
    p.write_text('{"quebrado": ', encoding="utf-8")
    with pytest.raises(arquivo.ArquivoCorrompido):
        arquivo.ler_json(str(p), [])
    assert (tmp_path / "c.json.corrompido").exists()
    assert arquivo.ler_json(str(p), [], tolerar_corrompido=True) == []


def test_ler_json_com_bom(tmp_path):
    p = tmp_path / "bom.json"
    p.write_bytes(b"\xef\xbb\xbf" + json.dumps({"a": 1}).encode())
    assert arquivo.ler_json(str(p)) == {"a": 1}


def test_jsonl_pula_linha_quebrada(tmp_path):
    p = str(tmp_path / "log.jsonl")
    arquivo.acrescentar_jsonl(p, {"a": 1})
    with open(p, "a", encoding="utf-8") as f:
        f.write('{"meia linha"\n')
    arquivo.acrescentar_jsonl(p, {"a": 2})
    assert arquivo.ler_jsonl(p) == [{"a": 1}, {"a": 2}]
    assert arquivo.ler_jsonl(str(tmp_path / "nao_existe.jsonl")) == []
