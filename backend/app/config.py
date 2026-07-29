from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Merged settings for the budgeting (Plaid) and investing (tastytrade) domains."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # --- budgeting: Plaid + PostgreSQL ---
    plaid_client_id: str = ""
    plaid_secret: str = ""
    plaid_env: str = "sandbox"
    plaid_products: str = "transactions"
    plaid_country_codes: str = "US"
    # Required by Plaid for OAuth institutions in native iOS Link. Must be an
    # HTTPS Universal Link registered in the Plaid Dashboard.
    plaid_redirect_uri: str = ""
    database_url: str = "postgresql+psycopg://127.0.0.1:5432/audel"
    # Optional development gate for exposing the local API through a tunnel.
    # When set, every /api route except /api/health requires this bearer token.
    app_api_key: str = ""

    # --- investing: tastytrade OAuth. "cert" = sandbox (safe); anything else = production. ---
    tastytrade_env: str = "cert"
    tastytrade_provider_secret: str = ""
    tastytrade_refresh_token: str = ""

    # --- AI copilot. Accepts either ANTHROPIC_API_KEY or CLAUDE_API_KEY in .env. ---
    anthropic_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("anthropic_api_key", "claude_api_key"),
    )
    assistant_model: str = "claude-sonnet-5"


@lru_cache
def get_settings() -> Settings:
    return Settings()
