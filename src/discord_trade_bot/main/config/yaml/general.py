from enum import StrEnum
from typing import ClassVar, override

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

from discord_trade_bot.main.config.yaml.discord import DiscordYamlConfig
from discord_trade_bot.main.config.yaml.exchange import ExchangeYamlConfig
from discord_trade_bot.main.config.yaml.state import StateYamlConfig
from discord_trade_bot.main.config.yaml.telegram import TelegramYamlConfig


class AppMode(StrEnum):
    """Application operating mode.

    Attributes:
        TESTNET: Use exchange testnet environments for testing.
        PRODUCTION: Use exchange production environments for live trading.
    """

    TESTNET = "testnet"
    PRODUCTION = "production"


class GeneralYamlConfig(BaseModel):
    """General application configuration.

    Attributes:
        mode: Operating mode (testnet or production). Defaults to testnet.
    """

    mode: AppMode = AppMode.TESTNET


class YamlSettings(BaseSettings):
    """Root configuration loaded from config.yaml.

    This class aggregates all YAML-based configuration sections including
    general settings, Discord sources, exchange settings, and more.

    Attributes:
        general: General application settings.
        discord: Discord channel watch configuration.
        exchanges: Per-exchange settings (timeout, testnet override).
        telegram: Telegram notification settings.
        state: State persistence configuration.
    """

    general: GeneralYamlConfig
    discord: DiscordYamlConfig
    exchanges: dict[str, ExchangeYamlConfig]
    telegram: TelegramYamlConfig
    state: StateYamlConfig

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(yaml_file="config.yaml", extra="ignore")

    @override
    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        return (YamlConfigSettingsSource(settings_cls),)
