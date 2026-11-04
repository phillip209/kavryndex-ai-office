"""Configuración leída de variables de entorno (prefijo ``OFFICE_``)."""

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="OFFICE_", env_file=".env", extra="ignore")

    env: str = "development"
    database_url: str = "sqlite:///./data/office.db"
    admin_api_key: SecretStr | None = None

    # Política de coste: con False, ningún proveedor marcado como de pago puede ejecutarse.
    allow_paid_providers: bool = False

    # Adaptador OpenAI-compatible (Ollama, Groq, Gemini...). Desactivado si base_url está vacío.
    openai_compat_base_url: str | None = None
    openai_compat_api_key: SecretStr | None = None
    openai_compat_is_paid: bool = True
    openai_compat_timeout_s: float = 60.0
    openai_compat_input_price_per_mtok: float = 0.0
    openai_compat_output_price_per_mtok: float = 0.0

    # Límites operativos
    max_tasks_per_project_run: int = 25
    memory_context_limit: int = 20
