import redis

from .config import settings

redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)


def ping() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False
