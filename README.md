# Discord Trade Bot

An automated cryptocurrency trading bot that monitors Discord channels for trading signals and executes trades on Binance and Bybit futures exchanges. Built with Clean Architecture principles, the bot features real-time position tracking, automatic stop-loss management, and take-profit execution.

## Features

- **Multi-Exchange Support**: Trade on Binance and Bybit futures markets
- **Discord Signal Monitoring**: Automatically parse and execute trading signals from Discord channels
- **Real-Time Position Tracking**: WebSocket-based order execution monitoring
- **Automatic Risk Management**:
  - Move stop-loss to breakeven after first take-profit
  - Configurable stop-loss and take-profit distribution
  - Position size management based on account balance
- **Telegram Notifications**: Get real-time updates on trade execution and position status
- **Asynchronous Task Processing**: Uses Taskiq with Redis for reliable background job processing
- **Clean Architecture**: Modular design with clear separation of concerns

## Architecture

The project follows Clean Architecture principles with the following layers:

```
src/discord_trade_bot/
├── core/
│   ├── domain/           # Business entities and domain logic
│   │   ├── entities/     # Position, Signal, TradeState
│   │   ├── services/     # Parser, TradingCalculations
│   │   └── value_objects/
│   └── application/      # Use cases and business logic
│       ├── signal/
│       │   └── use_cases/
│       │       └── processing.py    # ProcessSignalUseCase
│       └── trading/
│           └── use_cases/
│               ├── opening.py       # OpenPositionUseCase
│               └── tracking.py      # ProcessTrackerEventUseCase
├── infrastructure/       # External integrations
│   ├── discord/         # Discord client
│   ├── exchanges/       # Binance, Bybit adapters
│   ├── notifications/   # Telegram notifications
│   ├── persistence/     # SQLite repository
│   └── taskiq/          # Background task processing
├── main/                # Application setup
│   ├── config/          # Configuration management
│   ├── di/              # Dependency injection (Dishka)
│   └── runners/         # Discord and Tracker runners
└── presentation/        # CLI interface
```

## Prerequisites

- Python 3.14+
- Redis (for task queue)
- Discord account with access to signal channels
- Binance and/or Bybit API keys

## Installation

1. Clone the repository:
```bash
git clone <repository-url>
cd discord-trade-bot
```

2. Install dependencies using `uv`:
```bash
uv sync
```

Or using pip:
```bash
pip install -e .
```

3. Set up environment variables:
```bash
cp .env.dist .env
```

Edit `.env` and add your credentials:
```env
# Discord
DISCORD_TOKEN=your_discord_token_here

# Binance
BINANCE_API_KEY=your_binance_api_key
BINANCE_SECRET_KEY=your_binance_secret_key

# Bybit
BYBIT_API_KEY=your_bybit_api_key
BYBIT_SECRET_KEY=your_bybit_secret_key

# Telegram (optional)
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
TELEGRAM_CHAT_ID=your_telegram_chat_id

# Redis
REDIS_URL=redis://localhost:6379
```

4. Configure trading settings in `config.yaml`:
```yaml
general:
  mode: testnet  # or 'production'

discord:
  watch_sources:
    - source_id: discord_source_1
      enabled: true
      channel_id: YOUR_CHANNEL_ID
      exchange: binance
      free_balance_pct: 10
      fixed_leverage: 20
      default_sl_percent: 10
      tp_distribution:
        - label: tp1
          close_pct: 25
        - label: tp2
          close_pct: 25
        - label: tp3
          close_pct: 25
        - label: tp4
          close_pct: 25
```

## Usage

The bot consists of three main components that work together:

### 1. Discord Listener
Monitors Discord channels for trading signals:
```bash
discord-trade-bot discord
```

### 2. WebSocket Tracker
Tracks order execution and manages positions:
```bash
discord-trade-bot tracker
```

### 3. Taskiq Worker
Processes background tasks (signal processing, order execution):
```bash
discord-trade-bot worker
```

### Run All Components
For local development, start all components at once:
```bash
discord-trade-bot all
```

## Configuration

### Trading Settings

- **free_balance_pct**: Percentage of free balance to use per trade (default: 10%)
- **fixed_leverage**: Leverage multiplier (default: 20x)
- **default_sl_percent**: Default stop-loss percentage if not provided in signal (default: 10%)
- **tp_distribution**: How to distribute position size across take-profit levels

### Exchange Settings

Configure timeout and testnet mode for each exchange:
```yaml
exchanges:
  binance:
    timeout_seconds: 15
    testnet: true
  bybit:
    timeout_seconds: 15
    testnet: true
```

### Exchange Configuration

The bot supports multiple exchanges. You can configure one or both:

#### Binance
Required API permissions:
- Enable Futures
- Enable Reading

Leave `BINANCE_TOKEN` and `BINANCE_SECRET_KEY` empty in `.env` to skip Binance.

#### Bybit
Required API permissions:
- Read
- Trade
- WebSocket

Leave `BYBIT_TOKEN` and `BYBIT_SECRET_KEY` empty in `.env` to skip Bybit.

**Important:** At least one exchange must be configured for the bot to work.

## How It Works

1. **Signal Detection**: The Discord listener monitors configured channels for trading signals
2. **Signal Parsing**: Signals are parsed to extract symbol, side (LONG/SHORT), entry price, stop-loss, and take-profits
3. **Position Opening**: The bot calculates position size, sets leverage, and places market orders
4. **Order Tracking**: WebSocket tracker monitors order execution in real-time
5. **Risk Management**: 
   - After first TP hits, stop-loss moves to breakeven
   - Subsequent TPs are executed according to distribution
   - Position closes when all TPs hit or SL triggers

## Signal Format

The bot can parse various signal formats. Example:

```
🔥 BTCUSDT LONG
Entry: 45000
Stop Loss: 44000
TP1: 46000
TP2: 47000
TP3: 48000
TP4: 49000
```

## Development

### Project Structure

- **Domain Layer**: Pure business logic, no external dependencies
- **Application Layer**: Use cases orchestrating domain logic
- **Infrastructure Layer**: External service integrations
- **Presentation Layer**: CLI interface

### Running Tests

```bash
pytest tests/
```

### Code Quality

The project uses:
- **Ruff**: For linting and formatting
- **Basedpyright**: For type checking
- **Pytest**: For testing

Run linting:
```bash
ruff check src/
```

Format code:
```bash
ruff format src/
```

## Dependencies

Key dependencies:
- **discord.py-self**: Discord client
- **python-binance**: Binance API wrapper
- **pybit**: Bybit API wrapper
- **taskiq**: Distributed task queue
- **dishka**: Dependency injection framework
- **aiogram**: Telegram bot framework
- **aiosqlite**: Async SQLite database
- **pydantic**: Data validation

## Safety Features

- **Duplicate Position Prevention**: Won't open multiple positions for the same symbol on the same exchange
- **Balance Checks**: Validates sufficient balance before opening positions
- **Testnet Support**: Test strategies without risking real funds
- **Error Handling**: Comprehensive error handling and logging
- **Position Locking**: Prevents race conditions in position updates

## Notifications

The bot sends Telegram notifications for:
- Position opened
- Take-profit hit
- Stop-loss moved to breakeven
- Position closed
- Errors and warnings

## Logging

Logs are output to console with colored formatting. Log levels can be configured per module.

## Contributing

Contributions are welcome! Please follow the existing code style and architecture patterns.

## License

[Add your license here]

## Disclaimer

This bot is for educational purposes only. Cryptocurrency trading carries significant risk. Use at your own risk. The authors are not responsible for any financial losses incurred while using this software.

## Support

For issues and questions, please open an issue on GitHub.

## Roadmap

- [ ] Add support for spot trading
- [ ] Implement trailing stop-loss
- [ ] Add backtesting capabilities
- [ ] Web dashboard for monitoring
- [ ] Support for more exchanges (OKX, Kraken)
- [ ] Advanced signal pattern recognition
- [ ] Portfolio management features

## Author

**uzrama** - mark.uzun7@gmail.com

---

**Version**: 0.1.0  
**Last Updated**: March 2026
