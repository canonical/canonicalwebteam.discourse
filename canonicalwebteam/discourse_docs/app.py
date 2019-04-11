from canonicalwebteam.discourse_docs.blueprint import build_blueprint


class DiscourseDocs(object):
    def __init__(
        self,
        app=None,
        model=None,
        url_prefix="/docs",
        document_template="docs/document.html",
    ):
        self.app = app
        if app is not None:
            self.init_app(app, model, url_prefix)

    def init_app(
        self,
        app,
        model,
        url_prefix="/docs",
        document_template="docs/document.html",
    ):
        discourse_blueprint = build_blueprint(
            url_prefix, model, document_template
        )
        app.register_blueprint(discourse_blueprint, url_prefix=url_prefix)
