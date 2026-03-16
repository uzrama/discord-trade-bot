from typing import ClassVar, override

from pydantic import Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict, YamlConfigSettingsSource

from discord_trade_bot.main.config.env.binance import BinanceConfig
from discord_trade_bot.main.config.env.bybit import BybitConfig
from discord_trade_bot.main.config.env.discord import DiscordConfig
from discord_trade_bot.main.config.env.redis import RedisConfig
from discord_trade_bot.main.config.env.telegram import TelegramConfig
from discord_trade_bot.main.config.yaml.general import YamlSettings


class AppConfig(BaseSettings):
    yaml: YamlSettings = Field(default_factory=YamlSettings)  # pyright: ignore[reportArgumentType]
    binance: BinanceConfig = Field(default_factory=BinanceConfig)  # pyright: ignore[reportArgumentType]
    bybit: BybitConfig = Field(default_factory=BybitConfig)  # pyright: ignore[reportArgumentType]
    discord: DiscordConfig = Field(default_factory=DiscordConfig)  # pyright: ignore[reportArgumentType]
    telegram: TelegramConfig = Field(default_factory=TelegramConfig)  # pyright: ignore[reportArgumentType]
    redis: RedisConfig = Field(default_factory=RedisConfig)  # pyright: ignore[reportArgumentType]

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        yaml_file="config.yaml",
        env_file=".env",
        env_nested_delimiter="_",
        extra="ignore",
    )

    @override
    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            YamlConfigSettingsSource(settings_cls),
        )
