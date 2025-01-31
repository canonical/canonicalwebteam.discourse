import flask
import html
from requests.exceptions import HTTPError

from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
    RedirectFoundError,
    MetadataError,
    MarkdownError,
)

from canonicalwebteam.discourse.parsers.base_parser import BaseParser
import dateutil.parser
from bs4 import BeautifulSoup, element
from datetime import datetime


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
    Parsing and rendering of engage pages (parse_engage_pages) and
    takeovers (parse_takeovers)

    :param api: A DiscourseAPI for retrieving Discourse topics
    :param category_id: ID of a forum topic containing nav & URL map
    :param url_prefix: URL prefix on project (Default: /engage)
    :param page_type: ["engage-pages", "takeovers"]. This separation
           is necessary because metadata table is different for each.
    :param skip_posts: Skip given posts from throwing errors
    """

    def __init__(
        self,
        api,
        category_id,
        page_type,
        exclude_topics=[],
        additional_metadata_validation=[],
    ):
        self.api = api
        self.category_id = category_id
        self.page_type = page_type
        self.exclude_topics = exclude_topics
        self.additional_metadata_validation = additional_metadata_validation
        pass

    def get_index(
        self,
        limit=50,
        offset=0,
        key=None,
        value=None,
        second_key=None,
        second_value=None,
    ):
        """
        Get the index topic and split it into:
        - index document content
        - URL map
        And set those as properties on this object
        """
        if key == "tag":
            list_topics = self.api.get_engage_pages_by_tag(
                category_id=self.category_id,
                limit=limit,
                offset=offset,
                tag=value,
            )
        elif key and second_key:
            list_topics = self.api.get_engage_pages_by_param(
                category_id=self.category_id,
                limit=limit,
                offset=offset,
                key=key,
                value=value,
                second_key=second_key,
                second_value=second_value,
            )
        else:
            list_topics = self.api.get_engage_pages_by_param(
                category_id=self.category_id,
                limit=limit,
                offset=offset,
                key=key,
                value=value,
            )

        topics = []
        for topic in list_topics:
            if topic[6] not in self.exclude_topics:
                try:
                    topics_index = self.parse_topics(topic)
                    topics.append(topics_index)
                except MetadataError:
                    continue

        active_count = sum(item[9] for item in list_topics)
        try:
            # total_count is everything
            # active_count is active=true
            # current_total is the count returned after filtering
            total_count = list_topics[0][8]
            current_total = list_topics[0][10]
        except IndexError:
            total_count = 0
            current_total = 0

        # last column of list_topics is the total number of items
        # this is appended to every item
        return topics, total_count, active_count, current_total

    def get_engage_page(self, path):
        """
        Get single engage page using data-explorer
        """
        single_topic = self.api.get_engage_pages_by_param(
            category_id=self.category_id, key="path", value=path
        )
        try:
            single_topic[0]
        except KeyError:
            return None
        # No metadata found if single_topic = []
        except IndexError:
            return None

        metadata = self.parse_topics(single_topic[0])

        return metadata

    def get_engage_pages_tags(self):
        """
        Get all tags in all engage pages
        for the dropdown filter
        """
        list_topics = self.api.get_engage_pages_by_param(
            category_id=self.category_id, limit=-1
        )
        tags = set()
        for topic in list_topics:
            if topic[6] not in self.exclude_topics:
                try:
                    topics_index = self.parse_topics(topic)
                    if "tags" in topics_index:
                        tags = tags.union(set(topics_index["tags"].split(",")))
                except MetadataError:
                    continue

        return tags

    def parse_active_takeovers(self):
        active_takeovers_topics = self.api.get_engage_pages_by_param(
            category_id=self.category_id, key="active", value="true"
        )

        topics = []
        for topic in active_takeovers_topics:
            if topic[6] not in self.exclude_topics:
                try:
                    topics_index = self.parse_topics(topic)
                    topics.append(topics_index)
                except MetadataError:
                    continue

        return topics

    def process_ep_topic_soup(self, soup):
        """
        Given topic HTML soup, apply post-process steps
        """

        soup = self._replace_notifications(soup)
        soup = self._replace_notes_to_editors(soup)
        soup = self._replace_polls(soup)

        return soup

    def parse_topics(self, topic):
        """
        Parse topics in the given category and extract metadata
        to create an index

        Args:
        - topic: "cooked" post content

        returns:
        - topics: list
        """

        # Construct path using slug and id
        topic_path = f"{self.api.base_url}/t/{topic[7]}/{topic[6]}"

        updated_datetime = dateutil.parser.parse(topic[5])

        created_datetime = dateutil.parser.parse(topic[4])

        topic_soup = BeautifulSoup(topic[0], features="html.parser")

        metadata = {}

        # Does metadata table exist?
        try:
            topic_soup.contents[0]("th")[0].text
        except IndexError:
            error_message = f"{topic_path} metadata not found"
            raise MetadataError(error_message)

        if self.page_type == "takeovers":
            # Parse engage pages
            for row in topic_soup.contents[0]("tr"):
                # This condition skips the th key and value headers
                if len(row("td")) > 0:
                    try:
                        key = row("td")[0].contents[0]
                        value = row("td")[1].contents
                        # Allows metadata values to be empty
                        if len(value) == 0:
                            value = ""
                        elif len(value) > 0 and isinstance(
                            value[0], element.Tag
                        ):
                            tag_name = value[0].name
                            if tag_name == "a":
                                # Remove <a> links
                                value = value[0]["href"]
                            else:
                                value = value[0].string

                        else:
                            value = value[0]
                        metadata[key] = value
                    except Exception as error:
                        # Catch all metadata errors
                        error_message = (
                            f"{self.page_type} Metadata table contains errors:"
                            f" {error} for {topic_path}"
                        )
                        raise MetadataError(error_message)

            # Further metadata checks
            try:
                self.takeovers_healthcheck(metadata, topic[6])
            except MarkdownError:
                pass

            soup = self.process_ep_topic_soup(topic_soup)
            self._replace_lightbox(soup)

            first_table = soup.select_one("table:nth-of-type(1)")
            if (
                first_table.findAll("th")[0].getText() == "Key"
                and first_table.findAll("th")[1].getText() == "Value"
            ):
                first_table.decompose()

            # Combined metadata old index topic + topic metadata
            metadata.update(
                {
                    "updated": updated_datetime,
                    "created": created_datetime,
                    "topic_id": topic[6],
                    "topic_path": topic_path,
                }
            )
        else:
            # Parse engage pages
            for row in topic_soup.contents[0]("tr"):
                # This condition skips the th key and value headers
                if len(row("td")) > 0:
                    try:
                        key = row("td")[0].contents[0]
                        value = row("td")[1].contents
                        if len(value) == 0:
                            value = ""
                        elif len(value) > 0 and isinstance(
                            value[0], element.Tag
                        ):
                            # Remove <a> links
                            value = value[0].string
                        else:
                            value = value[0]
                        metadata[key] = value
                    except Exception as error:
                        error_message = (
                            "Metadata table contains errors:"
                            f" {error} for {topic_path}"
                        )
                        raise MetadataError(error_message)

            # Further metadata checks
            try:
                self.engage_pages_healthcheck(metadata, topic[6])
            except MarkdownError:
                pass

            soup = self.process_ep_topic_soup(topic_soup)
            self._replace_lightbox(soup)

            first_table = soup.select_one("table:nth-of-type(1)")
            if (
                first_table.findAll("th")[0].getText() == "Key"
                and first_table.findAll("th")[1].getText() == "Value"
            ):
                first_table.decompose()

            # Combined metadata old index topic + topic metadata
            metadata.update(
                {
                    "body_html": str(soup),
                    "updated": updated_datetime,
                    "created": created_datetime,
                    "topic_id": topic[6],
                    "topic_path": topic_path,
                }
            )

        return metadata

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

    def engage_pages_healthcheck(self, metadata, topic_id):
        """
        Check engage pages metadata (key/value table)
        for errors
        """
        errors = []

        if "path" not in metadata:
            error = (
                "Missing path on "
                f"https://discourse.ubuntu.com/t/{topic_id}."
                f" This engage page will not show in {self.page_type}"
            )
            errors.append(error)

        if "topic_name" not in metadata:
            error = (
                "Missing topic_name on "
                f"https://discourse.ubuntu.com/t/{topic_id}."
                " Default discourse title will be used"
            )
            errors.append(error)

        if "type" not in metadata:
            error = (
                "Missing type on "
                f"https://discourse.ubuntu.com/t/{topic_id}."
                " Provide a type for this engage page (whitepaper, "
                "webinar, blog, event etc)"
            )
            errors.append(error)

        if "active" not in metadata:
            error = (
                "Missing active on "
                f"https://discourse.ubuntu.com/t/{topic_id}."
                " Provide the active parameter in the metadata (true, false)"
            )
            errors.append(error)

        if "publish_date" in metadata:
            try:
                datetime(metadata["publish_date"])
            except TypeError:
                error = (
                    "publish_date must be a date"
                    " with the following format: yyyy-mm-dd"
                )

        for key in self.additional_metadata_validation:
            if key not in metadata:
                error = (
                    f"Missing {key} on "
                    f"https://discourse.ubuntu.com/t/{topic_id}. "
                    "This parameter is required to render takeovers"
                )
                errors.append(error)

        if len(errors) > 0:
            raise MarkdownError((", ").join(errors))

        pass

    def takeovers_healthcheck(self, metadata, topic_id, title=None):
        """
        Check takeovers metadata (key/value table)
        for errors
        """
        errors = []

        if "title" not in metadata:
            error = (
                "Missing title on "
                f"https://discourse.ubuntu.com/t/{topic_id}. "
                "This takeover will not be displayed"
            )
            errors.append(error)

        if "active" not in metadata:
            error = (
                "Missing active on "
                f"https://discourse.ubuntu.com/t/{topic_id}. "
                "This takeover will not be displayed"
            )
            errors.append(error)

        for key in self.additional_metadata_validation:
            if key not in metadata:
                error = (
                    f"Missing {key} on "
                    f"https://discourse.ubuntu.com/t/{topic_id}. "
                    "This parameter is required to render takeovers"
                )
                errors.append(error)

        if len(errors) > 0:
            raise MarkdownError((", ").join(errors))

        pass


class Category(Discourse):
    """
    Given a category id and CategoryParser takes any data tables found in the
    index topic and stores the data in a dictionary.
    Builds a URL map of all topics in the category.
    Returns a Flask view function to serve a topics from a Discourse category
    depending on the path.

    :param parser: A HTML parse class
    :param category_id: ID of a Discourse category
    :param url_prefix: URL prefix on project
    :param document_template: Path to a template to render page
    :param blueprint_name: Name of the Flask blueprint
    :param exclude_topics: Skip given posts from throwing errors
    """

    def __init__(
        self,
        parser,
        category_id,
        url_prefix,
        document_template,
        blueprint_name,
        exclude_topics=[],
    ):
        super().__init__(parser, document_template, url_prefix, blueprint_name)
        self.parser = parser
        self.category_id = category_id
        self.exclude_topics = exclude_topics
        self.category_topics = []
        self.parser.parse_index_topic()
        pass

        @self.blueprint.route("/")
        @self.blueprint.route("/<path:path>")
        def document_view(path=""):
            """
            A Flask view function to serve topics from a Discourse category
            """
            path = "/" + path
            if path == "/":
                document = self.parser.parse_topic(self.parser.index_topic)
            else:
                try:
                    topic_id = self._get_topic_id_from_path(path)
                except PathNotFoundError:
                    return flask.abort(404)

                if topic_id == self.parser.index_topic_id:
                    return flask.redirect(self.url_prefix)

                try:
                    topic = self.parser.api.get_topic(topic_id)
                except HTTPError as http_error:
                    return flask.abort(http_error.response.status_code)

                document = self.parser.parse_topic(topic)

            template = flask.render_template(
                document_template,
                category_index_metadata=self.parser.category_index_metadata,
                document=document,
            )
            return flask.make_response(template)

    def _get_topic_id_from_path(self, path):
        path = path.lstrip("/")
        category_topics = self._query_category_topics()
        for topic in category_topics:
            if topic[2] == path:
                return topic[0]
        return None

    def get_category_index_metadata(self, data_name):
        """
        Exposes an API to query category metadata

        :param data_name: Name of the data table
        """
        if data_name:
            return self.parser.category_index_metadata[data_name]
        else:
            return self.parser.category_index_metadata

    def get_topics_in_category(self):
        """
        Exposes an API to query all topics in a category
        """
        topics_list = self._query_category_topics()
        topics_map = {str(topic[0]): topic[2] for topic in topics_list}
        return topics_map

    def _query_category_topics(self):
        """
        Retrieve the category topics list from the api and store it.
        On subsequent calls, return the stored list.
        """
        if self.category_topics:
            return self.category_topics
        else:
            self.category_topics = self.parser.api.get_topic_list_by_category(
                self.category_id
            )
            return self.category_topics
