import taskiq_redis
from taskiq.serializers import MSGPackSerializer

from discord_trade_bot.main.config.app import AppConfig

config = AppConfig()
# Accessing config fields directly as per pydantic-settings
redis_url = config.redis.build_url(db=None)
broker = taskiq_redis.ListQueueBroker(url=redis_url).with_serializer(MSGPackSerializer())
