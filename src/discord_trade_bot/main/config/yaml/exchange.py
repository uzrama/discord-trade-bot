from pydantic import BaseModel


class ExchangeYamlConfig(BaseModel):
    """Per-exchange configuration from YAML.

    Attributes:
        timeout_seconds: API request timeout in seconds. Defaults to 15.
        testnet: Override global mode for this exchange. None means use general.mode.
        demo: Use demo/paper trading mode. None means use False by default.
    """

    timeout_seconds: int = 15
    testnet: bool | None = None  # None = use general.mode
    demo: bool | None = None  # None = use False by default
