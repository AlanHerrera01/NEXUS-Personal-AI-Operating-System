"""In-process rate limiting.

Token buckets keyed by ``(principal, route class)``, so a run-heavy caller is
limited differently from a caller spamming memory searches. Deliberately
in-process and in-memory: NEXUS runs as a single API process, and a shared Redis
store would be infrastructure this phase should not add. The trade-off is
explicit -- limits reset on restart and are per-process, so this bounds one
process's exposure, not a fleet's. Stated here rather than left to be
discovered.

Buckets are evicted when refilled, so an attacker cannot grow memory by cycling
distinct keys forever.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated_at: float


class RateLimitExceeded(Exception):
    """Raised when a bucket is empty. Carries when the caller may retry."""

    def __init__(self, scope: str, retry_after: float) -> None:
        super().__init__(f"rate limit exceeded for {scope}")
        self.scope = scope
        self.retry_after = max(1.0, retry_after)


class RateLimiter:
    """Token buckets, one per ``(scope, key)``.

    Thread-safe: FastAPI runs sync dependencies in a threadpool, so the lock is
    load-bearing rather than decorative.
    """

    def __init__(
        self,
        *,
        window_seconds: float = 60.0,
        max_buckets: int = 20_000,
        clock=time.monotonic,
    ) -> None:
        if window_seconds <= 0:
            raise ValueError("window_seconds must be greater than zero")
        if max_buckets < 1:
            raise ValueError("max_buckets must be at least 1")
        self.window_seconds = window_seconds
        self.max_buckets = max_buckets
        self._clock = clock
        self._buckets: dict[tuple[str, str], _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, scope: str, key: str, limit: int) -> None:
        """Consume one token, or raise :class:`RateLimitExceeded`.

        Raises rather than returning a boolean so a caller cannot accidentally
        treat "allowed" as advisory and proceed anyway.
        """
        if limit < 1:
            # A limit of zero configured by an operator is a mistake, not a
            # policy. Refusing everything would be fail-closed but useless;
            # raising here surfaces the misconfiguration at the first request.
            raise ValueError(f"rate limit for {scope} must be at least 1")
        self.consume(scope, key, limit)

    def consume(self, scope: str, key: str, limit: int) -> None:
        # Guarded in both entry points, because ``consume`` is public and a
        # division by the limit below would otherwise be reachable directly.
        if limit < 1:
            raise ValueError(f"rate limit for {scope} must be at least 1")
        now = self._clock()
        bucket_key = (scope, key)
        with self._lock:
            bucket = self._buckets.get(bucket_key)
            if bucket is None:
                bucket = _Bucket(tokens=float(limit), updated_at=now)
                self._buckets[bucket_key] = bucket
                self._evict_if_needed(now)
            else:
                elapsed = now - bucket.updated_at
                if elapsed > 0:
                    bucket.tokens = min(
                        float(limit), bucket.tokens + elapsed * (limit / self.window_seconds)
                    )
                    bucket.updated_at = now

            if bucket.tokens < 1.0:
                deficit = 1.0 - bucket.tokens
                retry_after = deficit * (self.window_seconds / limit)
                raise RateLimitExceeded(scope, retry_after)

            bucket.tokens -= 1.0

    def remaining(self, scope: str, key: str, limit: int) -> float:
        """Tokens left, for a ``X-RateLimit-Remaining`` header."""
        if limit < 1:
            raise ValueError(f"rate limit for {scope} must be at least 1")
        now = self._clock()
        with self._lock:
            bucket = self._buckets.get((scope, key))
            if bucket is None:
                return float(limit)
            elapsed = now - bucket.updated_at
            tokens = bucket.tokens
            if elapsed > 0:
                tokens = min(
                    float(limit), tokens + elapsed * (limit / self.window_seconds)
                )
            return max(0.0, tokens)

    def reset(self, scope: str | None = None, key: str | None = None) -> None:
        """Drop buckets. Tests use this instead of sleeping."""
        with self._lock:
            if scope is None:
                self._buckets.clear()
                return
            if key is None:
                for bucket_key in [k for k in self._buckets if k[0] == scope]:
                    del self._buckets[bucket_key]
                return
            self._buckets.pop((scope, key), None)

    def _evict_if_needed(self, now: float) -> None:
        """Bound the bucket table.

        Only runs when a *new* key appears, so a flood of distinct keys is the
        only thing that triggers it. Refilled buckets are the cheapest to drop
        because dropping them grants nothing: the caller simply starts a fresh
        allowance, which is what a refilled bucket would have given them anyway.
        """
        if len(self._buckets) <= self.max_buckets:
            return
        stale_before = now - self.window_seconds
        for bucket_key in [k for k, v in self._buckets.items() if v.updated_at < stale_before]:
            del self._buckets[bucket_key]
        if len(self._buckets) <= self.max_buckets:
            return
        overflow = len(self._buckets) - self.max_buckets
        for bucket_key in list(self._buckets)[:overflow]:
            del self._buckets[bucket_key]

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)


__all__ = ("RateLimitExceeded", "RateLimiter")