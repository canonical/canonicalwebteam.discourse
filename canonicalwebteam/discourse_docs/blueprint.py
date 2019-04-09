import flask
from requests.exceptions import HTTPError

from canonicalwebteam.discourse_docs.models import (
    NavigationParseError,
    RedirectFoundError,
)


def build_blueprint(url_prefix, model):

    blueprint = flask.Blueprint(
        "discourse",
        __name__,
        template_folder="/templates",
        static_folder="/static",
    )

    @blueprint.errorhandler(404)
    def page_not_found(e):
        try:
            frontpage, nav_html = model.parse_frontpage()
        except NavigationParseError as nav_error:
            nav_html = f"<p>{str(nav_error)}</p>"

        return flask.render_template("docs/404.html", nav_html=nav_html), 404

    @blueprint.errorhandler(410)
    def deleted(e):
        try:
            frontpage, nav_html = model.parse_frontpage()
        except NavigationParseError as nav_error:
            nav_html = f"<p>{str(nav_error)}</p>"

        return flask.render_template("docs/410.html", nav_html=nav_html), 410

    @blueprint.route("/")
    def homepage():
        """
        Redirect to the frontpage topic
        """

        frontpage, nav_html = model.parse_frontpage()

        if url_prefix != "/":
            return flask.redirect(url_prefix + frontpage["path"])
        else:
            return flask.redirect(frontpage["path"])

    @blueprint.route("/<path:path>")
    def document(path):
        try:
            document, nav_html = model.get_document(path)
        except RedirectFoundError as redirect_error:
            return flask.redirect(redirect_error.redirect_path)
        except HTTPError as http_error:
            flask.abort(http_error.response.status_code)
        except NavigationParseError as nav_error:
            document = nav_error.document
            nav_html = f"<p>{str(nav_error)}</p>"

        return flask.render_template(
            "docs/document.html",
            title=document["title"],
            body_html=document["body_html"],
            forum_link=document["forum_link"],
            updated=document["updated"],
            nav_html=nav_html,
        )

    return blueprint
