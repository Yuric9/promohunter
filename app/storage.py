import json
import threading
import time

from app.config import settings
from app.models import SearchConfig

_lock = threading.Lock()


def _caminho(nome):
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir / nome


def load_config() -> SearchConfig:
    arquivo = _caminho("config.json")
    if arquivo.exists():
        with open(arquivo, encoding="utf-8") as f:
            return SearchConfig(**json.load(f))
    return SearchConfig(termos=["iphone 15", "ps5", "air fryer"], preco_max=5000, desconto_min=20)


def save_config(cfg: SearchConfig):
    with open(_caminho("config.json"), "w", encoding="utf-8") as f:
        json.dump(cfg.model_dump(), f, indent=2, ensure_ascii=False)


def _ler_enviados() -> dict:
    arquivo = _caminho("enviados.json")
    if not arquivo.exists():
        return {}
    with open(arquivo, encoding="utf-8") as f:
        return json.load(f)


def ja_enviado(link: str) -> bool:
    """True se o link foi enviado dentro da janela de REENVIO_HORAS."""
    with _lock:
        enviado_em = _ler_enviados().get(link)
    return enviado_em is not None and time.time() - enviado_em < settings.reenvio_horas * 3600


def marcar_enviado(link: str):
    with _lock:
        enviados = _ler_enviados()
        limite = time.time() - settings.reenvio_horas * 3600
        enviados = {k: v for k, v in enviados.items() if v >= limite}
        enviados[link] = time.time()
        with open(_caminho("enviados.json"), "w", encoding="utf-8") as f:
            json.dump(enviados, f, indent=2)
