from pydantic import SecretStr

from discord_trade_bot.main.config.env.base import EnvSettings


class TelegramConfig(EnvSettings, env_prefix="TELEGRAM_"):
    token: SecretStr
