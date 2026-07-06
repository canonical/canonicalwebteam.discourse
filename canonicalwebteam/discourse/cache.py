"""In-process response cache with stale-on-error fallback for DiscourseAPI.

Discourse rate-limits API credentials (HTTP 429). Sites that fetch content
from Discourse on every page render exhaust that limit whenever crawlers
generate bursts of cache-miss traffic, turning every Discourse-backed page
into a 500.

ResponseCache bounds how often each unique request reaches Discourse:
fresh responses are served from memory, upstream errors are absorbed by
serving the last known value, and a rate limit with no fallback surfaces
as a typed RateLimitedError carrying Retry-After so consumers can return
a 503 instead of a 500.

The cache is per-process: each worker warms independently, so with the
default ttl a page costs at most one Discourse call per worker per five
minutes, regardless of traffic volume.
"""

# Standard library
import threading
import time

# Packages
from requests.exceptions import RequestException

# Local
from canonicalwebteam.discourse.exceptions import RateLimitedError

DEFAULT_RETRY_AFTER = 60
MAX_RETRY_AFTER = 600


# Statuses that mean the content is authoritatively gone: serving a
# stale copy would keep revoked (deleted/private) content public
REVOKED_STATUSES = (403, 404, 410)


def _retry_after_from(response):
    value = response.headers.get("Retry-After", "").strip()
    if value.isdecimal():
        value = min(int(value), MAX_RETRY_AFTER)
        return max(value, DEFAULT_RETRY_AFTER)
    return DEFAULT_RETRY_AFTER


class ResponseCache:
    """
    A TTL response cache with stale-on-error fallback.

    @param ttl: seconds a successful response is served from memory
    @param negative_ttl: seconds an empty response (None/[]/{}) is served;
        kept short so newly published content appears quickly
    @param max_size: entry cap; expired entries are dropped first, then
        the oldest half, so hot entries keep their stale fallback even
        under floods of unique keys
    @param error_retry: while Discourse is erroring, a stale entry is
        retried at most this often (seconds)
    """

    def __init__(
        self, ttl=300, negative_ttl=60, max_size=2000, error_retry=30
    ):
        self.ttl = ttl
        self.negative_ttl = negative_ttl
        self.max_size = max_size
        self.error_retry = error_retry
        # key -> (timestamp, value)
        self._entries = {}
        self._lock = threading.Lock()
        # Circuit breaker: one ResponseCache maps to one DiscourseAPI
        # instance (one API key, one quota), so a 429 anywhere opens a
        # cooldown for every key until Discourse recovers
        self._cooldown_until = 0.0

    def _open_cooldown(self, response):
        delay = max(_retry_after_from(response), DEFAULT_RETRY_AFTER)
        self._cooldown_until = time.monotonic() + delay

    def _remaining_cooldown(self):
        return max(1, int(self._cooldown_until - time.monotonic()))

    def cooldown_remaining(self):
        """
        Seconds left on an open circuit breaker, 0 when closed. Lets
        callers with uncached requests (e.g. freshness probes) respect
        the cooldown too.
        """
        if time.monotonic() < self._cooldown_until:
            return self._remaining_cooldown()
        return 0

    def report_rate_limit(self, response):
        """
        Open the circuit breaker for a 429 observed outside the cache
        """
        self._open_cooldown(response)

    def _serve_stale(self, key, entry):
        """
        Serve a stale entry, re-stamped so the next retry against a
        failing Discourse happens after ``error_retry`` seconds instead
        of on every request
        """
        backoff_timestamp = (
            time.monotonic() - self._ttl_for(entry[1]) + self.error_retry
        )
        with self._lock:
            self._entries[key] = (backoff_timestamp, entry[1])
        return entry[1]

    def _ttl_for(self, value):
        if value:
            return self.ttl
        return self.negative_ttl

    def _is_fresh(self, entry):
        timestamp, value = entry
        return time.monotonic() - timestamp < self._ttl_for(value)

    def _evict(self):
        """
        Make room without wiping hot entries: drop expired entries first,
        then the oldest half. Call with the lock held.
        """
        for key in [
            k
            for k, entry in self._entries.items()
            if not self._is_fresh(entry)
        ]:
            self._entries.pop(key, None)
        if len(self._entries) >= self.max_size:
            oldest = sorted(self._entries.items(), key=lambda item: item[1][0])
            for key, _ in oldest[: max(1, self.max_size // 2)]:
                self._entries.pop(key, None)

    def get(self, key, fetch):
        """
        Return the cached value for ``key``, refreshing via ``fetch()``
        when stale. On upstream failure the stale value is served and
        re-stamped so Discourse is retried at most every ``error_retry``
        seconds; an uncacheable 429 raises RateLimitedError.
        """
        entry = self._entries.get(key)
        if entry and self._is_fresh(entry):
            return entry[1]

        if time.monotonic() < self._cooldown_until:
            if entry:
                return entry[1]
            raise RateLimitedError(retry_after=self._remaining_cooldown())

        try:
            value = fetch()
        except RequestException as error:
            response = getattr(error, "response", None)
            status = None if response is None else response.status_code
            if status == 429:
                self._open_cooldown(response)
                if entry:
                    return self._serve_stale(key, entry)
                raise RateLimitedError(
                    retry_after=_retry_after_from(response)
                ) from error
            if status in REVOKED_STATUSES:
                # The content is gone or no longer public: drop the
                # cached copy instead of serving it stale
                with self._lock:
                    self._entries.pop(key, None)
                raise
            if entry:
                # Serve stale so transient upstream errors don't
                # break pages
                return self._serve_stale(key, entry)
            raise

        with self._lock:
            if len(self._entries) >= self.max_size:
                self._evict()
            self._entries[key] = (time.monotonic(), value)
        return value

    def invalidate(self, *key_prefix):
        """
        Drop the entry with this exact key, or every entry whose tuple
        key starts with the given prefix. Calling with no arguments
        clears the whole cache.
        """
        with self._lock:
            for key in [
                k for k in self._entries if k[: len(key_prefix)] == key_prefix
            ]:
                self._entries.pop(key, None)
