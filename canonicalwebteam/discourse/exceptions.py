import flask

# Initialize sentry_sdk if available
try:
    import sentry_sdk as _sentry_sdk
except ImportError:
    _sentry_sdk = None


def _capture_sentry_message(message):
    """
    Handle apps with both the new and old Sentry integrations,
    as well as apps without Sentry.

    - New style: ``sentry_sdk`` (Flask 2+, sentry-sdk package)
    - Old style: ``flask.current_app.extensions["sentry"]``
    (raven/Flask-Sentry)

    If neither is configured the message is silently dropped so that apps
    without Sentry don't crash.
    """
    if _sentry_sdk is not None and _sentry_sdk.is_initialized():
        _sentry_sdk.capture_message(message)
        return

    try:
        flask.current_app.extensions["sentry"].captureMessage(message)
    except (RuntimeError, KeyError, AttributeError):
        pass


class PathNotFoundError(Exception):
    """
    The URL path wasn't recognised
    """

    def __init__(self, path, *args, message=None, **kwargs):
        self.path = path

        if not message:
            message = f"Path {path} not found"

        super().__init__(message, *args, **kwargs)


class RedirectFoundError(Exception):
    """
    If we encounter redirects from Discourse, we need to take action
    """

    def __init__(self, path, target_url, *args, message=None, **kwargs):
        self.path = path
        self.target_url = target_url

        if not message:
            message = f"Path {path} has moved to {target_url}"

        super().__init__(*args, **kwargs)


class MetadataError(Exception):
    """
    If the metadata at the top of the post contains errors.
    These are errors enforced by the Web team for the
    metadata to follow a specific format
    """

    def __init__(self, *args: object) -> None:
        error_message = args[0]
        _capture_sentry_message(
            f"Engage pages metadata error: {error_message}"
        )
        pass


class MarkdownError(Exception):
    """
    If the content of the post contains errors.

    These are errors raised when the author of the post makes a
    Markdown error
    """

    def __init__(self, *args: object) -> None:
        error_message = args[0]
        _capture_sentry_message(f"Engage pages markdown error {error_message}")
        pass


class DataExplorerError(Exception):
    """
    Errors raised when the Data Explorer plugin for Discourse
    returns an error.

    Will be sent to Sentry
    """

    def __init__(self, *args: object) -> None:
        error_message = args[0]
        _capture_sentry_message(
            f"Engage pages Data Explorer error {error_message}"
        )
        pass


class DiscourseEventsError(Exception):
    """
    Error for the Discourse Events plugin.

    Will be sent to Sentry
    """

    def __init__(self, *args: object) -> None:
        error_message = args[0]
        _capture_sentry_message(
            f"Discourse event plugin error {error_message}"
        )
        pass


class MaxLimitError(Exception):
    """
    Error raised when limit/offset is too high
    most likely spamming.
    """

    pass
