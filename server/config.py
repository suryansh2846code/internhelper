"""Server settings (env-driven). Railway injects DATABASE_URL + secrets."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # SQLite locally, Postgres (from Railway) in production.
    database_url: str = "sqlite:///./data/app.db"
    jwt_secret: str = "dev-secret-change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 60 * 24 * 14  # 14 days

    # Where agents upload/read résumé files (local dir now; S3/R2 later)
    resume_dir: str = "./data/resumes"


settings = Settings()
