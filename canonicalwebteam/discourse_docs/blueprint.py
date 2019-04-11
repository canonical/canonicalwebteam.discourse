import flask
from requests.exceptions import HTTPError

from canonicalwebteam.discourse_docs.models import (
    NavigationParseError,
    RedirectFoundError,
)


def build_blueprint(url_prefix, model, document_template):

    blueprint = flask.Blueprint("discourse_docs", __name__)

    def redirect_handler(path):
        if url_prefix != "/":
            return flask.redirect(url_prefix + path)
        else:
            return flask.redirect(path)

    @blueprint.route("/")
    def homepage():
        """
        Redirect to the frontpage topic
        """
        frontpage, nav_html = model.parse_frontpage()
        return redirect_handler(frontpage["path"])

    @blueprint.route("/t/<path:path>")
    def redirect(path):
        return redirect_handler("/" + path)

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
            document_template,
            title=document["title"],
            body_html=document["body_html"],
            forum_link=document["forum_link"],
            updated=document["updated"],
            nav_html=nav_html,
        )

    return blueprint
