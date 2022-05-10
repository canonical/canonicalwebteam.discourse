import flask
import html
import os
from requests.exceptions import HTTPError
import dateutil.parser
import humanize
import flask
from bs4 import BeautifulSoup


from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
    RedirectFoundError,
    EngagePagesMetadataError
)
from canonicalwebteam.discourse.parsers.base_parser import BaseParser


class Discourse:
    def __init__(
        self,
        parser,
        document_template,
        url_prefix,
        blueprint_name,
    ):
        self.blueprint = flask.Blueprint(blueprint_name, __name__)
        self.url_prefix = url_prefix
        self.parser = parser

        @self.blueprint.route("/sitemap.txt")
        def sitemap_view():
            """
            Show a list of all URLs in the URL map
            """

            self.parser.parse()

            urls = []

            for key, value in self.parser.url_map.items():
                if type(key) is str:
                    urls.append(flask.request.host_url.strip("/") + key)

            return (
                "\n".join(urls),
                {"Content-Type": "text/plain; charset=utf-8"},
            )

        @self.blueprint.route("/sitemap.xml")
        def sitemap_xml():
            """
            Show a list of all URLs in the URL map
            """

            self.parser.parse()
            pages = []

            for key, value in self.parser.url_map.items():
                if type(key) is str:
                    try:
                        response = parser.api.get_topic(str(value))
                        last_updated = response["post_stream"]["posts"][0][
                            "updated_at"
                        ]
                    except Exception:
                        last_updated = None

                    pages.append(
                        {
                            "url": html.escape(
                                flask.request.host_url.strip("/") + key
                            ),
                            "last_updated": last_updated,
                        }
                    )

            from jinja2 import Template

            tm = Template(
                '<?xml version="1.0" encoding="utf-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
                'xmlns:xhtml="http://www.w3.org/1999/xhtml">'
                "{% for page in pages %}"
                "<url>"
                "<loc>{{ page['url'] }}</loc>"
                "<changefreq>weekly</changefreq>"
                "<lastmod>{{ page['last_updated'] }}</lastmod>"
                "</url>"
                "{% endfor %}"
                "</urlset>"
            )
            xml_sitemap = tm.render(pages=pages)

            response = flask.make_response(xml_sitemap)
            response.headers["Content-Type"] = "application/xml"
            response.headers["Cache-Control"] = "public, max-age=43200"

            return response

    def init_app(self, app):
        """
        Attach the discourse docs blueprint to the application
        at the specified `url_prefix`
        """

        app.register_blueprint(self.blueprint, url_prefix=self.url_prefix)

    def _set_parser_warnings(self, response):
        """
        Append parser warnings to the reponse headers

        :param response: A flask response object
        """

        # To not make the response too big
        # we show only the last ten warnings
        warnings = self.parser.warnings[-10:]

        for message in warnings:
            flask.current_app.logger.warning(message)
            response.headers.add(
                "discourse-warning",
                message,
            )

        # Reset parser warnings
        self.parser.warnings = []

        return response


class Docs(Discourse):
    """
    A Flask extension object to create a Blueprint
    to serve documentation pages, pulling the documentation content
    from Discourse.

    :param api: A DiscourseAPI for retrieving Discourse topics
    :param index_topic_id: ID of a forum topic containing nav & URL map
    :param url_prefix: URL prefix for hosting under (Default: /docs)
    :param document_template: Path to a template for docs pages
                              (Default: docs/document.html)
    """

    def __init__(
        self,
        parser,
        document_template="docs/document.html",
        url_prefix="/docs",
        blueprint_name="docs",
    ):
        super().__init__(parser, document_template, url_prefix, blueprint_name)

        @self.blueprint.route("/")
        @self.blueprint.route("/<path:path>")
        def document_view(path=""):
            """
            A Flask view function to serve
            topics pulled from Discourse as documentation pages.
            """
            docs_version = ""
            path = "/" + path
            self.parser.parse()

            if path == "/":
                document = self.parser.parse_topic(self.parser.index_topic)
            else:
                try:
                    topic_id, docs_version = self.parser.resolve_path(path)
                except RedirectFoundError as redirect:
                    return flask.redirect(redirect.target_url)
                except PathNotFoundError:
                    return flask.abort(404)

                if topic_id == self.parser.index_topic_id:
                    return flask.redirect(self.url_prefix)

                try:
                    topic = self.parser.api.get_topic(topic_id)
                except HTTPError as http_error:
                    return flask.abort(http_error.response.status_code)

                document = self.parser.parse_topic(topic, docs_version)

                if (
                    topic_id not in self.parser.url_map_versions[docs_version]
                    and document["topic_path"] != path
                ):
                    return flask.redirect(document["topic_path"])

            version_paths = self.parser.resolve_path_all_versions(
                path, docs_version
            )

            response = flask.make_response(
                flask.render_template(
                    document_template,
                    document=document,
                    versions=self.parser.versions,
                    navigation=self.parser.navigation,
                    forum_url=self.parser.api.base_url,
                    metadata=self.parser.metadata,
                    docs_version=docs_version,
                    version_paths=version_paths,
                )
            )

            return self._set_parser_warnings(response)


class Tutorials(Discourse):
    """
    A Flask extension object to create a Blueprint
    to serve documentation pages, pulling the documentation content
    from Discourse.

    :param api: A DiscourseAPI for retrieving Discourse topics
    :param index_topic_id: ID of a forum topic containing nav & URL map
    :param url_prefix: URL prefix for hosting under (Default: /docs)
    :param document_template: Path to a template for docs pages
                              (Default: docs/document.html)
    """

    def __init__(
        self,
        parser,
        document_template="tutorials/tutorial.html",
        url_prefix="/tutorials",
        blueprint_name="tutorials",
    ):
        super().__init__(parser, document_template, url_prefix, blueprint_name)

        @self.blueprint.route("/")
        @self.blueprint.route("/<path:path>")
        def document_view(path=""):
            """
            A Flask view function to serve
            topics pulled from Discourse as documentation pages.
            """

            path = "/" + path
            self.parser.parse()

            if path == "/":
                document = self.parser.parse_topic(self.parser.index_topic)
            else:
                try:
                    topic_id = self.parser.resolve_path(path)
                except RedirectFoundError as redirect:
                    return flask.redirect(redirect.target_url)
                except PathNotFoundError:
                    return flask.abort(404)

                if topic_id == self.parser.index_topic_id:
                    return flask.redirect(self.url_prefix)

                try:
                    topic = self.parser.api.get_topic(topic_id)
                except HTTPError as http_error:
                    return flask.abort(http_error.response.status_code)

                document = self.parser.parse_topic(topic)

                if (
                    topic_id not in self.parser.url_map
                    and document["topic_path"] != path
                ):
                    return flask.redirect(document["topic_path"])

            response = flask.make_response(
                flask.render_template(
                    document_template,
                    document=document,
                    forum_url=self.parser.api.base_url,
                    metadata=self.parser.metadata,
                    tutorials=self.parser.tutorials,
                )
            )

            return self._set_parser_warnings(response)


class EngagePages(BaseParser):
    """
    A Flask extension object to create a Blueprint
    to serve exclusively engage pages, pulling the documentation content
    from Discourse.

    :param api: A DiscourseAPI for retrieving Discourse topics
    :param index_topic_id: ID of a forum topic containing nav & URL map
    :param url_prefix: URL prefix for hosting under (Default: /engage)
    :param document_template: Path to a template for docs pages
                              (Default: docs/document.html)
    """

    def __init__(
        self,
        parser,
        document_template="engage/base.html",
        url_prefix="/engage",
        blueprint_name="engage-pages",
    ):
        super().__init__(parser, document_template, url_prefix, blueprint_name)
        self.topics_index = []

        # def document_view(path=""):
        #     """
        #     A Flask view function to serve
        #     topics pulled from Discourse as documentation pages.
        #     """

        #     path = "/" + path
        #     self.topics_index = self.parser.parse()

        #     if path == "/":
        #         return self.topics_index
        #     else:
        #         preview = flask.request.args.get("preview")

        #         try:
        #             topic_id = self.parser.resolve_path(path, topics)
        #         except PathNotFoundError:
        #             return flask.abort(404)

        #         try:
        #             topic = self.parser.api.get_topic(topic_id)
        #         except HTTPError as http_error:
        #             return flask.abort(http_error.response.status_code)

        #         document = self.parser.parse_topic(topic)

        #         if (
        #             preview is None
        #             and "active" in document["metadata"]
        #             and document["metadata"]["active"] == "false"
        #         ):
        #             return flask.redirect(
        #                 f"{self.parser.api.base_url}{document['topic_path']}"
        #             )

        #     return {
        #         "document": document,
        #         "forum_url": self.parser.api.base_url,
        #     }

    def parse(self):
        """
        Get the index topic and split it into:
        - index document content
        - URL map
        And set those as properties on this object
        """
        list_topics = self.api.get_engage_pages(51)
        topics = []
        for topic in list_topics:
            try:
                topics_index = self.get_topics_index(topic)
                topics.append(topics_index)
            except EngagePagesMetadataError:
                continue
        

        return topics

    def get_topics_index(self, topic):
        """
        Parse topics in the given category and extract metadata
        to create an index

        Args:
        - topic: "cooked" post content

        returns:
        - topics: list
        """
        # No cooked content means hidden post
        if topic[0] == "":
            raise EngagePagesMetadataError(f"/t/{topic[6]}/{topic[5]}")

        updated_datetime = dateutil.parser.parse(
            topic[4]
        )

        created_datetime = dateutil.parser.parse(
            topic[3]
        )

        # Construct path using slug and id
        topic_path = f"{self.api.base_url}/t/{topic[6]}/{topic[5]}"

        topic_soup = BeautifulSoup(
            topic[0], features="html.parser"
        )

        self.current_topic = None
        metadata = []

        # Does metadata table exist?
        try:
            topic_soup.contents[0]("th")[0].text
        except IndexError:
            raise EngagePagesMetadataError(topic_path,"Metadata not found on ")

        for row in topic_soup.contents[0]("tr"):
            metadata.append(cell.text for cell in row("td"))

        # Further metadata checks
        self.metadata_healthcheck(metadata, topic[5])

        # if metadata_healthcheck:
        metadata.pop(0)

        soup = self._process_topic_soup(topic_soup)
        self._replace_lightbox(soup)
        sections = self._get_sections(soup)
        self.current_topic = {
            "title": topic[2],
            "body_html": str(soup),
            "sections": sections,
            "updated": updated_datetime,
            "created": created_datetime,
            "topic_id": topic[5],
            "topic_path": topic_path,
            "metadata": metadata
        }


        return self.current_topic


    def parse_topic(self, topic):
        """
        Parse a topic object of Engage pages category from the Discourse API
        and return document data:
        - title: The title of the engage page
        - body_html: The HTML content of the initial topic post
            (with some post-processing)
        - updated: A human-readable date, relative to now
            (e.g. "3 days ago")
        - topic_path: relative path of the topic
        """

        updated_datetime = dateutil.parser.parse(
            topic[3]
        )

        # Construct path using slug and id
        topic_path = f"/t/{topic[4]}/{topic[5]}"

        topic_soup = BeautifulSoup(
            topic[0], features="html.parser"
        )

        self.current_topic = {}
        content = []
        warnings = []
        metadata = []

        for row in topic_soup.contents[0]("tr"):
            metadata.append([cell.text for cell in row("td")])

        if metadata:
            metadata.pop(0)
            self.current_topic.update(metadata)
            content = topic_soup.contents
            # Remove takeover metadata table
            content.pop(0)
        else:
            warnings.append("Metadata could not be parsed correctly")

        # Find URL in order to find tags of current topic
        # current_topic_path = next(
        #     path for path, id in self.url_map.items() if id == topic["id"]
        # )
        self.current_topic_metadata = next(
            (
                item
                for item in self.metadata
                if item["path"] == current_topic_path
            ),
        )

        # Combine metadata from index with individual pages
        self.current_topic_metadata.update(self.current_topic)

        # Expose related topics for thank-you pages
        # This will make it available for the instance
        # rather than the view
        current_topic_related = self._parse_related(
            self.current_topic_metadata["tags"]
        )

        return {
            "title": topic["title"],
            "metadata": self.current_topic_metadata,
            "body_html": content,
            "created": humanize.naturaltime(
                updated_datetime.replace(tzinfo=None)
            ),
            "updated": humanize.naturaltime(
                updated_datetime.replace(tzinfo=None)
            ),
            "related": current_topic_related,
            "topic_path": topic_path,
        }

    def resolve_path(self, relative_path, topics):
        """
        Given a path to a Discourse topic, and a mapping of
        URLs to IDs and IDs to URLs, resolve the path to a topic ID

        A PathNotFoundError will be raised if the path is not recognised.
        """

        full_path = os.path.join(self.url_prefix, relative_path.lstrip("/"))

        if full_path in self.url_map:
            topic_id = self.url_map[full_path]
        else:
            raise PathNotFoundError(relative_path)

        return topic_id

    def get_topic(self, topic_id):
        """
        Receives a single topic_id and
        @return the content of the topic
        """
        index_topic = self.api.get_topic(topic_id)
        return self.parse_topic(index_topic)

    def _parse_related(self, tags):
        """
        Filter index topics by tag
        This provides a list of "Related engage pages"
        """
        index_list = [item for item in self.metadata if item["tags"] in tags]
        return index_list
    
    def metadata_healthcheck(self, metadata, topic_id, title=None):
        """
        Type check engage pages metadata (key, value table)
        for errors
        """
        errors = []
        if "path" not in metadata:
            error = f"Missing path for '{title}' on https://discourse.ubuntu.com/t/{topic_id}. This engage page will not show in /engage"
            errors.append(error)
        
        if not title:
            error = "Missing title for https://discourse.ubuntu.com/t/{topic_id}. Default discourse title will be used"
            errors.append(error)

        if len(errors) > 0:
            flask.current_app.extensions["sentry"].captureMessage((", ").join(errors))
            return False
        return True
