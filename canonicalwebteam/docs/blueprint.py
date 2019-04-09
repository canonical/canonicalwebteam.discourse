from urllib.parse import urlparse, urlunparse, unquote

import flask
from requests.exceptions import HTTPError
from canonicalwebteam.yaml_responses.flask_helpers import (
    prepare_deleted,
    prepare_redirects,
)

from canonicalwebteam.discourse.models import (
    DiscourseDocs,
    NavigationParseError,
    RedirectFoundError,
)


def build_blueprint(discourse_url, frontpage_id, category_id):

    discourse_blueprint = flask.Blueprint(
        "discourse",
        __name__,
        template_folder="/templates",
        static_folder="/static",
    )

    discourse = DiscourseDocs(
        base_url=discourse_url,
        frontpage_id=frontpage_id,
        category_id=category_id,
    )

    # Parse redirects.yaml and permanent-redirects.yaml
    discourse_blueprint.before_request(prepare_redirects())

    def deleted_callback(context):
        try:
            frontpage, nav_html = discourse.parse_frontpage()
        except NavigationParseError as nav_error:
            nav_html = f"<p>{str(nav_error)}</p>"

        return (
            flask.render_template(
                "docs/410.html", nav_html=nav_html, **context
            ),
            410,
        )

    discourse_blueprint.before_request(
        prepare_deleted(view_callback=deleted_callback)
    )

    @discourse_blueprint.errorhandler(404)
    def page_not_found(e):
        try:
            frontpage, nav_html = discourse.parse_frontpage()
        except NavigationParseError as nav_error:
            nav_html = f"<p>{str(nav_error)}</p>"

        return flask.render_template("docs/404.html", nav_html=nav_html), 404

    @discourse_blueprint.errorhandler(410)
    def deleted(e):
        return deleted_callback({})

    @discourse_blueprint.errorhandler(500)
    def server_error(e):
        return flask.render_template("docs/500.html"), 500

    @discourse_blueprint.before_request
    def clear_trailing():
        """
        Remove trailing slashes from all routes
        We like our URLs without slashes
        """

        parsed_url = urlparse(unquote(flask.request.url))
        path = parsed_url.path

        if path != "/" and path.endswith("/"):
            new_uri = urlunparse(parsed_url._replace(path=path[:-1]))

            return flask.redirect(new_uri)

    @discourse_blueprint.route("/")
    def homepage():
        """
        Redirect to the frontpage topic
        """

        frontpage, nav_html = discourse.parse_frontpage()

        return flask.redirect("/ddocs" + frontpage["path"])

    @discourse_blueprint.route("/<path:path>")
    def document(path):
        try:
            document, nav_html = discourse.get_document(path)
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

    return discourse_blueprint
