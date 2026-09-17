from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg2://suyuan:suyuan@db:5432/suyuan"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret: str = "suyuan-fang-dev-secret-change-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 8
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    class Config:
        env_prefix = "APP_"
        env_file = ".env"


settings = Settings()
