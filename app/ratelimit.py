"""Token bucket rate limiting in Redis.

The whole read-refill-decrement runs as one Lua script, so two requests can never both
take the last token. Redis's own clock (TIME) is used, so API replicas with skewed
clocks agree. If Redis is unreachable the limiter fails open: rate limiting protects
capacity, while money correctness is guaranteed by PostgreSQL.
"""

import logging
import math

import redis

from app.problems import ProblemError
from app.redis_client import redis_client

log = logging.getLogger(__name__)

TOKEN_BUCKET_LUA = """
local key = KEYS[1]
local rate = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local t = redis.call('TIME')
local now = tonumber(t[1]) + tonumber(t[2]) / 1000000

local state = redis.call('HMGET', key, 'tokens', 'ts')
local tokens = tonumber(state[1]) or burst
local ts = tonumber(state[2]) or now
tokens = math.min(burst, tokens + math.max(0, now - ts) * rate)

local allowed = 0
local retry_ms = 0
if tokens >= 1 then
  tokens = tokens - 1
  allowed = 1
else
  retry_ms = math.ceil((1 - tokens) / rate * 1000)
end

redis.call('HSET', key, 'tokens', tostring(tokens), 'ts', tostring(now))
redis.call('PEXPIRE', key, math.ceil(burst / rate * 1000) + 1000)
return {allowed, retry_ms}
"""

_script = redis_client.register_script(TOKEN_BUCKET_LUA)


def take_token(scope: str, ident: str, *, rate: float, burst: int) -> tuple[bool, float]:
    """Return (allowed, retry_after_seconds)."""
    try:
        allowed, retry_ms = _script(keys=[f"rl:{scope}:{ident}"], args=[rate, burst])
    except redis.RedisError as exc:
        log.warning("rate limiter unavailable, failing open: %s", exc.__class__.__name__)
        return True, 0.0
    return bool(allowed), retry_ms / 1000


def enforce(scope: str, ident: str, *, rate: float, burst: int) -> None:
    allowed, retry_after = take_token(scope, ident, rate=rate, burst=burst)
    if not allowed:
        raise ProblemError(
            429,
            "rate limit exceeded",
            headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
        )
