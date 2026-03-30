# Docker Deployment Guide

Complete guide for deploying Discord Trade Bot using Docker and Docker Compose.

## 📋 Table of Contents

- [Quick Start](#quick-start)
- [Prerequisites](#prerequisites)
- [Configuration](#configuration)
- [Production Deployment](#production-deployment)
- [Development Setup](#development-setup)
- [Commands Reference](#commands-reference)
- [Logging](#logging)
- [Troubleshooting](#troubleshooting)
- [Architecture](#architecture)

---

## 🚀 Quick Start

### Production Deployment

```bash
# 1. Copy environment file
cp .env.docker .env

# 2. Edit .env with your credentials
nano .env

# 3. Build and start all services
docker-compose up -d

# 4. View logs
docker-compose logs -f
```

### Development Setup

```bash
# 1. Copy environment file
cp .env.docker .env

# 2. Edit .env with your credentials
nano .env

# 3. Start in development mode (with hot-reload)
docker-compose -f docker-compose.dev.yml up

# 4. View logs
docker-compose -f docker-compose.dev.yml logs -f
```

---

## 📦 Prerequisites

- **Docker**: 20.10+ ([Install Docker](https://docs.docker.com/get-docker/))
- **Docker Compose**: 2.0+ ([Install Docker Compose](https://docs.docker.com/compose/install/))
- **Discord Token**: From [Discord Developer Portal](https://discord.com/developers/applications)
- **Exchange API Keys**: Binance and/or Bybit API credentials

---

## ⚙️ Configuration

### 1. Environment Variables

Copy the example environment file:

```bash
cp .env.docker .env
```

Edit `.env` and configure:

**Required:**
- `DISCORD_TOKEN` - Your Discord bot token
- `BYBIT_TOKEN` + `BYBIT_SECRET_KEY` OR `BINANCE_TOKEN` + `BINANCE_SECRET_KEY`

**Optional:**
- `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` - For notifications
- `REDIS_PASSWORD` - Redis password (leave empty for no auth)

**Example `.env`:**

```env
# Redis (Docker Compose)
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_PASSWORD=
REDIS_TASKIQ_DB=0

# Discord
DISCORD_TOKEN=your_discord_token_here

# Bybit
BYBIT_TOKEN=your_bybit_api_key
BYBIT_SECRET_KEY=your_bybit_secret_key

# Telegram (optional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### 2. Trading Configuration

Edit `config.yaml` to configure:

- Discord channels to monitor
- Trading parameters (leverage, position size, etc.)
- Take-profit distributions
- Risk management settings

See [README.md](README.md) for detailed configuration options.

---

## 🏭 Production Deployment

### Build and Start

```bash
# Build images
docker-compose build

# Start all services in background
docker-compose up -d

# Verify all services are running
docker-compose ps
```

### Expected Output

```
NAME                        STATUS              PORTS
discord-bot-listener        Up (healthy)        
discord-bot-tracker         Up (healthy)        
discord-bot-worker          Up (healthy)        
discord-bot-redis           Up (healthy)        6379/tcp
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f discord-bot
docker-compose logs -f tracker
docker-compose logs -f worker

# Last 100 lines
docker-compose logs --tail=100 -f
```

### Stop Services

```bash
# Stop all services
docker-compose down

# Stop and remove volumes (⚠️ deletes database)
docker-compose down -v
```

---

## 🔧 Development Setup

Development mode includes:
- Hot-reload for code changes
- Debug logging enabled
- Exposed Redis port (6379)
- Interactive terminal (stdin/tty)

### Start Development Environment

```bash
# Start all services
docker-compose -f docker-compose.dev.yml up

# Start specific service
docker-compose -f docker-compose.dev.yml up discord-bot

# Rebuild after dependency changes
docker-compose -f docker-compose.dev.yml build
```

### Run Tests

```bash
# Run all tests
docker-compose -f docker-compose.dev.yml run --rm discord-bot pytest

# Run specific test file
docker-compose -f docker-compose.dev.yml run --rm discord-bot pytest tests/domain/test_parser.py

# Run with coverage
docker-compose -f docker-compose.dev.yml run --rm discord-bot pytest --cov=discord_trade_bot
```

### Code Quality Checks

```bash
# Linting
docker-compose -f docker-compose.dev.yml run --rm discord-bot ruff check src/

# Type checking
docker-compose -f docker-compose.dev.yml run --rm discord-bot basedpyright src/

# Format code
docker-compose -f docker-compose.dev.yml run --rm discord-bot ruff format src/
```

---

## 📚 Commands Reference

### Docker Compose Commands

```bash
# Build images
docker-compose build [service]

# Start services
docker-compose up -d [service]

# Stop services
docker-compose stop [service]

# Restart services
docker-compose restart [service]

# View logs
docker-compose logs -f [service]

# Execute command in running container
docker-compose exec [service] [command]

# Run one-off command
docker-compose run --rm [service] [command]

# Show service status
docker-compose ps

# Remove stopped containers
docker-compose down
```

### Service Names

- `redis` - Redis server
- `discord-bot` - Discord listener
- `tracker` - WebSocket tracker
- `worker` - Taskiq worker

### Examples

```bash
# Restart only the worker
docker-compose restart worker

# View Discord bot logs
docker-compose logs -f discord-bot

# Execute shell in Discord bot container
docker-compose exec discord-bot bash

# Check Redis connection
docker-compose exec redis redis-cli ping
```

---

## 📊 Logging

### Log Configuration

All services use JSON file logging with:
- **Max size**: 10MB per file
- **Max files**: 3 files (rotation)
- **Total storage**: ~30MB per service

### View Logs

```bash
# Real-time logs (all services)
docker-compose logs -f

# Real-time logs (specific service)
docker-compose logs -f discord-bot

# Last 100 lines
docker-compose logs --tail=100

# Logs since timestamp
docker-compose logs --since 2026-03-30T10:00:00

# Logs with timestamps
docker-compose logs -f -t
```

### Log Levels

**Production** (default):
- INFO level for normal operations
- ERROR level for failures

**Development**:
- DEBUG level for detailed information
- Set via `LOG_LEVEL=DEBUG` environment variable

### Export Logs

```bash
# Export all logs to file
docker-compose logs > bot-logs.txt

# Export specific service logs
docker-compose logs discord-bot > discord-bot-logs.txt

# Export with timestamps
docker-compose logs -t > bot-logs-with-time.txt
```

---

## 🔍 Troubleshooting

### Services Not Starting

**Check logs:**
```bash
docker-compose logs
```

**Common issues:**
- Missing `.env` file → Copy from `.env.docker`
- Invalid API credentials → Check Discord/Exchange tokens
- Redis not ready → Wait for health check to pass

### Redis Connection Failed

```bash
# Check Redis is running
docker-compose ps redis

# Test Redis connection
docker-compose exec redis redis-cli ping

# Restart Redis
docker-compose restart redis
```

### Database Issues

```bash
# Check database file permissions
docker-compose exec discord-bot ls -la /app/data/

# Reset database (⚠️ deletes all data)
docker-compose down -v
docker-compose up -d
```

### Container Keeps Restarting

```bash
# Check container logs
docker-compose logs [service]

# Check health status
docker-compose ps

# Inspect container
docker inspect discord-bot-listener
```

### Out of Memory

```bash
# Check container resource usage
docker stats

# Increase Docker memory limit in Docker Desktop settings
# Or add memory limits to docker-compose.yml:
services:
  discord-bot:
    mem_limit: 512m
```

### Permission Denied Errors

```bash
# Fix file permissions
sudo chown -R 1000:1000 ./data/

# Or run as root (not recommended)
docker-compose exec -u root discord-bot bash
```

---

## 🏗️ Architecture

### Container Structure

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network                        │
│                     (bot-network)                        │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐ │
│  │ Discord Bot  │  │   Tracker    │  │    Worker    │ │
│  │  (Listener)  │  │  (WebSocket) │  │   (Taskiq)   │ │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘ │
│         │                  │                  │          │
│         └──────────────────┼──────────────────┘          │
│                            │                             │
│                     ┌──────▼───────┐                    │
│                     │     Redis    │                    │
│                     │  (Task Queue)│                    │
│                     └──────────────┘                    │
│                                                          │
└─────────────────────────────────────────────────────────┘

External:
  - Discord API
  - Binance/Bybit API
  - Telegram API (optional)

Volumes:
  - bot-data (SQLite database)
  - redis-data (Redis persistence)
```

### Service Responsibilities

**Discord Bot (Listener)**
- Monitors Discord channels
- Parses trading signals
- Dispatches tasks to worker

**Tracker (WebSocket)**
- Listens to exchange WebSocket streams
- Tracks order execution
- Manages position updates

**Worker (Taskiq)**
- Processes trading signals
- Executes orders
- Manages risk (SL/TP)

**Redis**
- Task queue for Taskiq
- Message broker between services

### Data Flow

```
Discord Message → Discord Bot → Redis Queue → Worker → Exchange API
                                                  ↓
                                            SQLite Database
                                                  ↓
Exchange WebSocket → Tracker → Redis Queue → Worker → Update Position
```

---

## 🔒 Security Best Practices

1. **Never commit `.env` file** - Contains sensitive credentials
2. **Use strong Redis password** - Set `REDIS_PASSWORD` in production
3. **Run as non-root user** - Containers use `botuser` (UID 1000)
4. **Read-only config** - `config.yaml` mounted as read-only
5. **Network isolation** - Services communicate via internal network
6. **Regular updates** - Keep Docker images updated

---

## 📈 Monitoring

### Health Checks

All services have health checks:

```bash
# Check health status
docker-compose ps

# Inspect health check
docker inspect discord-bot-listener | grep -A 10 Health
```

### Resource Usage

```bash
# Real-time resource monitoring
docker stats

# Container resource limits
docker-compose config
```

---

## 🆘 Support

- **Issues**: [GitHub Issues](https://github.com/uzrama/discord-trade-bot/issues)
- **Documentation**: [README.md](README.md)
- **Email**: mark.uzun7@gmail.com

---

## 📝 License

See [LICENSE](LICENSE) file for details.

---

**Last Updated**: March 30, 2026  
**Version**: 0.1.0
