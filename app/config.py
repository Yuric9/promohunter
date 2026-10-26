from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = ""
    cors_origins: str = "http://localhost:3000"

    ml_country: str = "MLB"
    ml_access_token: str = ""

    shopee_app_id: str = ""
    shopee_secret: str = ""

    whatsapp_provider: str = "evolution"
    evolution_api_url: str = "http://localhost:8080"
    evolution_api_key: str = ""
    evolution_instance: str = "promohunter"
    whatsapp_default_number: str = ""
    whatsapp_default_group_id: str = ""

    data_dir: Path = Path("data")
    reenvio_horas: int = 24

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
