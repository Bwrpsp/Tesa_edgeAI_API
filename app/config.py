import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    APP_NAME: str = "TopGun Benchmark Server"
    ENV: str = "development"
    
    # Security
    ADMIN_API_KEY: str = "topgun_admin_super_secret_key"
    
    # Database (defaults to local SQLite with aiosqlite, easily swap to postgresql+asyncpg://...)
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/topgun.db"
    
    # Competition Rules
    DEFAULT_TEST_QUOTA: int = 5
    # Default initial mode: "all" (both train & test active), "train", "test", or "paused"
    DEFAULT_GLOBAL_MODE: str = "all"
    
    # Maximum seconds allowed between finishing image transfer and JSON submission (0 = no limit)
    MAX_SUBMISSION_WINDOW_SECONDS: int = 0
    
    # Paths
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data"
    
    # AWS S3 Settings (optional: if empty, local filesystem is used)
    AWS_REGION: str = "us-east-1"
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    S3_IMAGE_BUCKET: str = ""
    S3_SUBMISSION_BUCKET: str = ""
    
    # Streaming
    STREAM_CHUNK_SIZE: int = 64 * 1024  # 64 KB

    @property
    def is_s3_enabled(self) -> bool:
        return bool(self.S3_IMAGE_BUCKET or self.S3_SUBMISSION_BUCKET)


settings = Settings()
