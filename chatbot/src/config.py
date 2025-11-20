import os


class Config:
    CHAT_BOT_API_KEY = os.getenv("CHAT_BOT_API_KEY")
    PORT_API_HOST = os.getenv("PORT_API_HOST", "NOT_SET")
    PORT_API_CONTAINER = os.getenv("PORT_API_CONTAINER", "NOT_SET")
    DB_NAME = os.getenv("DB_NAME", "NOT_SET")
    DB_USER = os.getenv("DB_USER", "NOT_SET")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "NOT_SET")
    DB_HOST = os.getenv("DB_HOST", "NOT_SET")
    BOT_TOKEN = os.getenv("BOT_TOKEN", "NOT_SET")
    API_HOST = os.getenv("API_HOST", "NOT_SET")
    API_ADMIN_USERNAME = os.getenv("API_ADMIN_USERNAME", "NOT_SET")
    API_ADMIN_PASSWORD = os.getenv("API_ADMIN_PASSWORD", "NOT_SET")
    SENTRY_DSN = os.getenv("SENTRY_DSN_CHATBOT", "NOT_SET")

    def __setattr__(self, key, value):
        raise Exception("new values should not be set manually")


def get_config() -> Config:
    config = Config()
    return config
