class PathNotFoundError(Exception):
    """
    The URL path wasn't recognised
    """

    def __init__(self, path, *args, message=None, **kwargs):
        self.path = path

        if not message:
            message = f"Path {path} not found"

        super().__init__(message, *args, **kwargs)
