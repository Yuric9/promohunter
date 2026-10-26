import secrets
from typing import Optional

from fastapi import Header, HTTPException

from app.config import settings


def exigir_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Bloqueia a requisição se API_KEY estiver definida e o header não bater."""
    if not settings.api_key:
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, settings.api_key):
        raise HTTPException(status_code=401, detail="API key inválida ou ausente")
