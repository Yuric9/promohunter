import importlib.util
from pathlib import Path

ARQUIVO = Path(__file__).resolve().parent.parent / "PromoHunter.pyw"


def carregar(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_loader("launcher", loader=None)
    mod = importlib.util.module_from_spec(spec)
    mod.__file__ = str(ARQUIVO)
    exec(compile(ARQUIVO.read_text(encoding="utf-8"), str(ARQUIVO), "exec"), mod.__dict__)
    monkeypatch.setattr(mod, "PASTA", tmp_path)
    monkeypatch.setattr(mod, "ENV", tmp_path / ".env")
    return mod


def test_gera_api_key_no_lugar_do_placeholder(tmp_path, monkeypatch):
    mod = carregar(tmp_path, monkeypatch)
    (tmp_path / ".env.example").write_text("API_KEY=troque-por-uma-chave-secreta\nML_COUNTRY=MLB\n")
    mod.garantir_env()
    chave = mod.ler_api_key()
    assert len(chave) > 20 and chave != mod.CHAVE_PLACEHOLDER
    assert "ML_COUNTRY=MLB" in (tmp_path / ".env").read_text()
    mod.garantir_env()
    assert mod.ler_api_key() == chave  # não troca uma chave que já existe
