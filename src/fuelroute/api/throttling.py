"""Rate limiting that lets requests through when its counter store is down."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from redis.exceptions import RedisError
from rest_framework.throttling import AnonRateThrottle

if TYPE_CHECKING:
    from rest_framework.request import Request
    from rest_framework.views import APIView

__all__ = ["FailOpenAnonRateThrottle"]

logger = logging.getLogger(__name__)


class FailOpenAnonRateThrottle(AnonRateThrottle):
    """Limits anonymous clients, and allows the request when the cache cannot count it.

    Refusing every request because Redis is unreachable would turn a cache outage into
    a full outage; the provider's own quota still caps the damage.
    """

    def allow_request(self, request: Request, view: APIView) -> bool:
        """Return the throttle's decision, or ``True`` when the counter store fails."""
        try:
            return super().allow_request(request, view)
        except RedisError as error:
            logger.warning("rate limit store failed, request allowed: %s", type(error).__name__)
            return True
