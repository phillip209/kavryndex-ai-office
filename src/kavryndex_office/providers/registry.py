from kavryndex_office.config import Settings
from kavryndex_office.errors import BudgetExceededError, NotFoundError
from kavryndex_office.providers.anthropic import AnthropicProvider
from kavryndex_office.providers.base import LLMProvider
from kavryndex_office.providers.mock import MockProvider
from kavryndex_office.providers.openai_compat import OpenAICompatProvider


class ProviderRegistry:
    """Proveedores disponibles + política de coste."""

    def __init__(self, *, allow_paid: bool) -> None:
        self._providers: dict[str, LLMProvider] = {}
        self.allow_paid = allow_paid

    def register(self, provider: LLMProvider) -> None:
        self._providers[provider.name] = provider

    def names(self) -> list[str]:
        return sorted(self._providers)

    def get(self, name: str) -> LLMProvider:
        provider = self._providers.get(name)
        if provider is None:
            raise NotFoundError(f"Proveedor '{name}' no configurado")
        if provider.is_paid and not self.allow_paid:
            raise BudgetExceededError(
                f"Proveedor '{name}' es de pago y OFFICE_ALLOW_PAID_PROVIDERS=false"
            )
        return provider


def build_registry(settings: Settings) -> ProviderRegistry:
    registry = ProviderRegistry(allow_paid=settings.allow_paid_providers)
    registry.register(MockProvider())
    if settings.openai_compat_base_url:
        key = settings.openai_compat_api_key
        registry.register(
            OpenAICompatProvider(
                base_url=settings.openai_compat_base_url,
                api_key=key.get_secret_value() if key else None,
                is_paid=settings.openai_compat_is_paid,
                timeout_s=settings.openai_compat_timeout_s,
                input_price_per_mtok=settings.openai_compat_input_price_per_mtok,
                output_price_per_mtok=settings.openai_compat_output_price_per_mtok,
            )
        )
    if settings.anthropic_api_key and settings.anthropic_api_key.get_secret_value():
        prices = (settings.anthropic_input_price_per_mtok, settings.anthropic_output_price_per_mtok)
        if prices[0] is None or prices[1] is None:
            raise ValueError(
                "Anthropic requiere OFFICE_ANTHROPIC_INPUT_PRICE_PER_MTOK y "
                "OFFICE_ANTHROPIC_OUTPUT_PRICE_PER_MTOK para registrar costes"
            )
        registry.register(
            AnthropicProvider(
                api_key=settings.anthropic_api_key.get_secret_value(),
                input_price_per_mtok=prices[0],
                output_price_per_mtok=prices[1],
                base_url=settings.anthropic_base_url,
                timeout_s=settings.anthropic_timeout_s,
            )
        )
    return registry
