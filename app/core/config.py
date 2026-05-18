# Path: backend/app/core/config.py

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # DB
    DATABASE_URL: str = "sqlite:///./medicalend.db"

    # API meta
    PROJECT_NAME: str = "MediCalend API"
    API_V1_PREFIX: str = "/api/v1"

    # Environment
    ENVIRONMENT: str = "local"

    # CORS
    BACKEND_CORS_ORIGINS: str = (
        "http://localhost,"
        "http://localhost:3000,"
        "http://localhost:3001,"
        "http://localhost:5173,"
        "https://medicalend-web.vercel.app,"
        "https://app.medicalend.ro"
    )

    # JWT / Auth
    SECRET_KEY: str = "CHANGE_THIS_LATER_TO_A_LONG_RANDOM_STRING"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24

    # Action tokens
    EMAIL_VERIFY_TOKEN_EXPIRE_HOURS: int = 24
    PASSWORD_RESET_TOKEN_EXPIRE_MINUTES: int = 60

    # App URLs for e-mail links
    FRONTEND_VERIFY_EMAIL_URL: str = "medicalend://verify-email"
    FRONTEND_RESET_PASSWORD_URL: str = "medicalend://reset-password"

    # Web app URL
    FRONTEND_WEB_URL: str = "http://localhost:3001"

    # Google OAuth / Calendar integration
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_OAUTH_REDIRECT_URI: str = (
        "http://localhost:8000/api/v1/integrations/google-calendar/oauth/callback"
    )
    GOOGLE_OAUTH_STATE_SECRET: str = "CHANGE_THIS_GOOGLE_STATE_SECRET"

    # SMTP
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_USE_TLS: bool = True
    MAIL_FROM: str = "no-reply@medicalend.local"
    MAIL_FROM_NAME: str = "MediCalend"

    @property
    def cors_origins_list(self) -> list[str]:
        return [
            origin.strip()
            for origin in self.BACKEND_CORS_ORIGINS.split(",")
            if origin.strip()
        ]

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()