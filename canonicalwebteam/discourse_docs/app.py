from canonicalwebteam.discourse_docs.blueprint import build_blueprint
from canonicalwebteam.discourse_docs.models import DiscourseApi


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
        discourse = DiscourseApi(
            base_url=discourse_url,
            frontpage_id=frontpage_id,
            category_id=category_id,
        )

        discourse_blueprint = build_blueprint(url_prefix, discourse)
        app.register_blueprint(discourse_blueprint, url_prefix=url_prefix)
