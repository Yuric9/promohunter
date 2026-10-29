import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = ""
    cors_origins: str = "http://localhost:3000"

    ml_country: str = "MLB"
    ml_access_token: str = ""
    # Aplicativo grátis do portal de desenvolvedores do Mercado Livre (não é afiliado):
    # com eles o robô pega sozinho uma chave de acesso nova a cada execução
    ml_client_id: str = ""
    ml_client_secret: str = ""

    shopee_app_id: str = ""
    shopee_secret: str = ""

    serpapi_key: str = ""

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_dono: str = ""  # número do seu usuário no Telegram (libera o robô de conversa)

    data_dir: Path = Path("data")
    reenvio_horas: int = 24
    # Promoção real: preço de hoje pelo menos QUEDA_MIN% abaixo da mediana que o robô viu antes,
    # com pelo menos HISTORICO_MIN_DIAS dias de histórico (0 = não confere o histórico)
    historico_min_dias: int = 3
    queda_min: int = 10
    # Passagens de blogs conferidas no Google Voos: no máximo N buscas da SerpApi por dia
    verificacoes_dia: int = 4

    @property
    def telegram_destino(self) -> str:
        """Aceita '@canal', 'canal', 't.me/canal', 'https://t.me/canal' ou o id numérico (-100...)."""
        valor = self.telegram_chat_id.strip().strip('"').strip("'")
        valor = re.sub(r"^(https?://)?(www\.)?(t|telegram)\.(me|dog)/", "", valor).split("?")[0].strip("/")
        if valor and not valor.startswith(("@", "-", "+")) and not valor.lstrip("-").isdigit():
            valor = "@" + valor
        return valor

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
