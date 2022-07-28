import flask


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
        flask.current_app.extensions["sentry"].captureMessage(
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
        flask.current_app.extensions["sentry"].captureMessage(
            f"Engage pages markdown error {error_message}"
        )
        pass


class DataExplorerError(Exception):
    pass
