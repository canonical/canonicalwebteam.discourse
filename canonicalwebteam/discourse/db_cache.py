"""Postgres-backed response cache for DiscourseAPI.

Discourse rate-limits API credentials (HTTP 429). An in-process cache
doesn't help much when an app runs many workers across many pods: each
one warms independently and hammers Discourse on its own first request.

DBResponseCache stores each response in a shared Postgres table instead,
so every worker/pod of an app sees one copy:

- No entry yet: fetch with no timeout (block as long as it takes), store
  it, return it.
- Entry younger than ``ttl``: return it straight from the table, no HTTP
  call at all.
- Entry ``ttl`` or older: refresh it, bounded to ``refresh_timeout``
  seconds. A timeout, a 429, or any other request failure falls back to
  the stale entry instead of failing the request.

A refresh is claimed with a single atomic UPDATE before the HTTP call is
made, so when an entry crosses ``ttl`` only one worker across the whole
fleet actually calls Discourse -- everyone else serves the stale value
they already have. A failed refresh leaves a short-lived provisional
timestamp behind as a backoff, so the next attempt (by any worker) waits
``error_retry`` seconds rather than being retried on every request.
"""

import logging
from datetime import timedelta

from requests.exceptions import RequestException, Timeout
from sqlalchemy import (
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    delete,
    func,
    literal,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB, insert
from sqlalchemy.exc import DBAPIError, ProgrammingError

from canonicalwebteam.discourse.exceptions import RateLimitedError

logger = logging.getLogger(__name__)

# ASCII unit separator: joins/terminates key segments so invalidate()'s
# prefix matching can't confuse "a segment ending in 5" with "a shorter
# prefix that happens to end in the same digits"
_KEY_DELIMITER = "\x1f"

_metadata = MetaData()

_discourse_cache_table = Table(
    "discourse_cache",
    _metadata,
    # One DiscourseAPI instance (base_url + Data Explorer query ids) per
    # namespace, so several instances can safely share one table
    Column("namespace", String, primary_key=True),
    Column("cache_key", String, primary_key=True),
    Column("value", JSONB, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)


def _encode_segment(segment):
    text = str(segment)
    return text.replace("\\", "\\\\").replace(
        _KEY_DELIMITER, "\\" + _KEY_DELIMITER
    )


def _encode_key(key):
    """
    Encode a tuple key as a delimited string, each segment terminated by
    the delimiter, so a shorter key tuple's encoding is always a clean
    prefix of a longer one that starts with the same segments.
    """
    return "".join(
        _encode_segment(segment) + _KEY_DELIMITER for segment in key
    )


def _escape_like(text):
    """Escape a literal string for safe use inside a LIKE pattern"""
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _retry_after_from(response):
    value = response.headers.get("Retry-After", "").strip()
    if value.isdecimal():
        return int(value)
    return 60


class DBResponseCache:
    """
    A Postgres-backed response cache shared across every worker/pod that
    points at the same database.

    @param engine: a SQLAlchemy Engine the caller creates and owns
        (shared across every DBResponseCache instance in the app)
    @param namespace: identifies this DiscourseAPI instance's rows in the
        shared table -- use a distinct namespace per instance (e.g. one
        per base_url / Data Explorer query id combination)
    @param ttl: how long a stored entry is served without refreshing
    @param refresh_timeout: seconds allowed for a refresh fetch before
        falling back to the stale entry
    @param error_retry: after a failed refresh, how long before another
        worker will attempt the next one
    """

    def __init__(
        self,
        engine,
        namespace,
        ttl=timedelta(hours=6),
        refresh_timeout=8,
        error_retry=30,
    ):
        self.engine = engine
        self.namespace = namespace
        self.ttl = ttl
        self.refresh_timeout = refresh_timeout
        self.error_retry = timedelta(seconds=error_retry)
        self.table = _discourse_cache_table
        self._ensure_table()

    def _ensure_table(self):
        try:
            _metadata.create_all(
                self.engine, tables=[self.table], checkfirst=True
            )
        except ProgrammingError as error:
            # Lost a race with another worker/pod creating the table at
            # the same time -- the table exists either way.
            pgcode = getattr(getattr(error, "orig", None), "pgcode", None)
            if (
                pgcode != "42P07"
                and "already exists" not in str(error).lower()
            ):
                raise

    def get(self, key, fetch):
        """
        Return the cached value for ``key``, calling ``fetch(timeout=...)``
        when there's no entry yet (unbounded) or the entry is stale
        (bounded to ``refresh_timeout``). See module docstring for the
        full policy.
        """
        table = self.table
        cache_key = _encode_key(key)

        try:
            with self.engine.begin() as conn:
                row = conn.execute(
                    select(
                        table.c.value,
                        (
                            table.c.updated_at > func.now() - literal(self.ttl)
                        ).label("is_fresh"),
                    ).where(
                        table.c.namespace == self.namespace,
                        table.c.cache_key == cache_key,
                    )
                ).first()
        except DBAPIError as error:
            logger.error(
                "Discourse DB cache unavailable (%s): falling back to a "
                "direct, bounded fetch for %r",
                error,
                key,
            )
            return self._fetch_bounded(fetch)

        if row is None:
            return self._fetch_and_store(cache_key, key, fetch)

        value, is_fresh = row
        if is_fresh:
            return value

        return self._refresh(cache_key, key, value, fetch)

    def _fetch_and_store(self, cache_key, key, fetch):
        """No entry exists yet: fetch with no timeout, store, return."""
        try:
            value = fetch(timeout=None)
        except RequestException as error:
            self._raise_if_rate_limited(error)
            raise

        self._upsert(cache_key, value)
        return value

    def _refresh(self, cache_key, key, stale_value, fetch):
        """
        Entry is stale: claim it with one atomic UPDATE so only one
        worker across the fleet refreshes it, then try a bounded fetch,
        falling back to the stale value on timeout/429/any other failure.
        """
        table = self.table
        try:
            with self.engine.begin() as conn:
                claimed = conn.execute(
                    update(table)
                    .where(
                        table.c.namespace == self.namespace,
                        table.c.cache_key == cache_key,
                        table.c.updated_at <= func.now() - literal(self.ttl),
                    )
                    .values(
                        updated_at=(
                            func.now()
                            - literal(self.ttl)
                            + literal(self.error_retry)
                        )
                    )
                    .returning(table.c.value)
                ).first()
        except DBAPIError as error:
            logger.error(
                "Discourse DB cache unavailable (%s): serving stale copy "
                "for %r without attempting a refresh",
                error,
                key,
            )
            return stale_value

        if claimed is None:
            # Another worker/pod already claimed this refresh
            logger.info(
                "Discourse refresh for %r already claimed elsewhere: "
                "serving stale copy",
                key,
            )
            return stale_value

        try:
            value = fetch(timeout=self.refresh_timeout)
        except Timeout:
            logger.warning(
                "Discourse refresh for %r took longer than %ss: serving "
                "stale copy",
                key,
                self.refresh_timeout,
            )
            return stale_value
        except RequestException as error:
            response = getattr(error, "response", None)
            status = None if response is None else response.status_code
            if status == 429:
                logger.warning(
                    "Discourse returned 429 refreshing %r: serving stale "
                    "copy",
                    key,
                )
            else:
                logger.warning(
                    "Discourse refresh for %r failed (%s): serving stale "
                    "copy",
                    key,
                    error,
                )
            return stale_value

        self._upsert(cache_key, value)
        return value

    def _upsert(self, cache_key, value):
        table = self.table
        stmt = insert(table).values(
            namespace=self.namespace,
            cache_key=cache_key,
            value=value,
            updated_at=func.now(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[table.c.namespace, table.c.cache_key],
            set_={
                "value": stmt.excluded.value,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        try:
            with self.engine.begin() as conn:
                conn.execute(stmt)
        except DBAPIError as error:
            logger.error(
                "Discourse DB cache unavailable (%s): fetched value "
                "could not be stored, will be re-fetched next time",
                error,
            )

    def _fetch_bounded(self, fetch):
        """DB is unreachable: no cache, just a bounded direct fetch."""
        try:
            return fetch(timeout=self.refresh_timeout)
        except RequestException as error:
            self._raise_if_rate_limited(error)
            raise

    def _raise_if_rate_limited(self, error):
        response = getattr(error, "response", None)
        status = None if response is None else response.status_code
        if status == 429:
            raise RateLimitedError(
                retry_after=_retry_after_from(response)
            ) from error

    def invalidate(self, *key_prefix):
        """
        Drop the entry with this exact key, or every entry whose tuple
        key starts with the given prefix. Calling with no arguments
        clears every entry in this namespace.
        """
        table = self.table
        with self.engine.begin() as conn:
            if not key_prefix:
                conn.execute(
                    delete(table).where(table.c.namespace == self.namespace)
                )
                return
            pattern = _escape_like(_encode_key(key_prefix)) + "%"
            conn.execute(
                delete(table).where(
                    table.c.namespace == self.namespace,
                    table.c.cache_key.like(pattern, escape="\\"),
                )
            )
