from pydantic import SecretStr

from discord_trade_bot.main.config.env.base import EnvSettings


class DiscordConfig(EnvSettings, env_prefix="DISCORD_"):
    token: SecretStr
