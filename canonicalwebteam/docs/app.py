from canonicalwebteam.docs.blueprint import build_blueprint


class DiscourseExtension(object):
    def __init__(
        self,
        app=None,
        url_prefix=None,
        discourse_url=None,
        frontpage_id=None,
        category_id=None,
    ):
        self.app = app
        if app is not None:
            self.init_app(
                app, url_prefix, discourse_url, frontpage_id, category_id
            )

    def init_app(
        self, app, url_prefix, discourse_url, frontpage_id, category_id
    ):
        discourse_blueprint = build_blueprint(
            url_prefix, discourse_url, frontpage_id, category_id
        )
        app.register_blueprint(discourse_blueprint, url_prefix=url_prefix)
        app.url_map.strict_slashes = False
