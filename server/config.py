"""Server settings (env-driven). Railway injects DATABASE_URL + secrets."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite locally, Postgres (from Railway) in production.
    database_url: str = "sqlite:///./data/app.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 60 * 24 * 14      # 14 days (web session)
    pairing_token_ttl_min: int = 15               # device pairing window
    agent_key_ttl_min: int = 60 * 24 * 365        # 1 year (paired device key)
    agent_online_secs: int = 40                   # heartbeat freshness for "online"

    # Where agents upload/read résumé files (local dir now; S3/R2 later)
    resume_dir: str = "./data/resumes"


settings = Settings()
