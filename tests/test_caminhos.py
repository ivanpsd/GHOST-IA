import os

from ghost.nucleo import caminhos


def test_raiz_e_a_pasta_do_projeto():
    assert os.path.isdir(os.path.join(caminhos.RAIZ, "ghost", "nucleo"))
    assert caminhos.dado("x.json") == os.path.join(caminhos.RAIZ, "dados", "x.json")
    assert caminhos.modelo("piper", "a.onnx") == os.path.join(caminhos.RAIZ, "modelos", "piper", "a.onnx")


def test_migrar_move_sem_sobrescrever(tmp_path, monkeypatch):
    for nome in ("RAIZ", "DADOS", "LOGS", "MODELOS", "PRINTS"):
        sub = "" if nome == "RAIZ" else nome.lower()
        monkeypatch.setattr(caminhos, nome, str(tmp_path / sub) if sub else str(tmp_path))
    (tmp_path / "memoria_ghost.json").write_text("antigo", encoding="utf-8")
    (tmp_path / "ghost.log").write_text("log", encoding="utf-8")
    os.makedirs(tmp_path / "dados")
    (tmp_path / "pessoas.json").write_text("antigo", encoding="utf-8")
    (tmp_path / "dados" / "pessoas.json").write_text("novo", encoding="utf-8")

    assert caminhos.migrar() == 3
    assert (tmp_path / "dados" / "memoria_ghost.json").read_text(encoding="utf-8") == "antigo"
    assert (tmp_path / "logs" / "ghost.log").exists()
    assert (tmp_path / "dados" / "pessoas.json").read_text(encoding="utf-8") == "novo"            # não sobrescreve
    assert (tmp_path / "dados" / "pessoas.json.antigo").read_text(encoding="utf-8") == "antigo"   # nem perde
    assert not (tmp_path / "pessoas.json").exists()                                                # raiz limpa
    assert caminhos.migrar() == 0                                                                  # idempotente
