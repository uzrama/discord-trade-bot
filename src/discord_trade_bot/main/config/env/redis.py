from pydantic import SecretStr

from .base import EnvSettings


class RedisConfig(EnvSettings, env_prefix="REDIS_"):
    host: str
    password: SecretStr
    port: int
    taskiq_db: int

    def build_url(self, db: int | None = None) -> str:
        target_db = db if db is not None else self.taskiq_db
        return f"redis://:{self.password.get_secret_value()}@{self.host}:{self.port}/{target_db}"
