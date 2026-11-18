"""Shared Redis client. Short timeouts so a Redis outage cannot stall requests."""

import redis

from app.config import get_settings

redis_client = redis.Redis.from_url(
    get_settings().redis_url,
    decode_responses=True,
    socket_timeout=1,
    socket_connect_timeout=1,
)
