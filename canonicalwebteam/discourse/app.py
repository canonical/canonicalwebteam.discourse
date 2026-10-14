import flask
import html
import logging
from requests.exceptions import HTTPError

from werkzeug.exceptions import ServiceUnavailable

from canonicalwebteam.discourse.exceptions import (
    PathNotFoundError,
    RateLimitedError,
    RedirectFoundError,
    MetadataError,
    MarkdownError,
)

from canonicalwebteam.discourse.models import _normalise_tags
from canonicalwebteam.discourse.parsers.base_parser import (
    BaseParser,
    LANGUAGE_MAP,
    normalize_link,
)
import dateutil.parser
from bs4 import BeautifulSoup, element
from datetime import datetime
from slugify import slugify

logger = logging.getLogger(__name__)


URL_METADATA_KEYS = {
    "meta_copydoc",
    "meta_image",
    "image",
    "primary_link",
    "resource_url",
}


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
                except RateLimitedError as rate_error:
                    raise ServiceUnavailable(
                        retry_after=rate_error.retry_after
                    ) from rate_error
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
                except RateLimitedError as rate_error:
                    raise ServiceUnavailable(
                        retry_after=rate_error.retry_after
                    ) from rate_error
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
        self.category_last_updated = None

    def _refresh_if_stale(self):
        """
        On an edit to this category, drop its cached engage entries so
        the next fetch re-parses fresh. Engage pages have no per-page
        freshness signal, so this lets edits appear without shortening
        the shared TTL.

        Probes the category directly (not check_for_category_updates) so
        invalidation stays scoped to this category's engage keys and
        never the shared events/category/topic-list entries. Best-effort:
        a rate-limited probe is expected while the breaker is open (INFO,
        no traceback); anything else is logged with a traceback.
        """
        try:
            most_recent = self.api.get_categories_last_activity_time(
                self.category_id
            )[0][1]
        except RateLimitedError:
            logger.info(
                "EngagePages freshness probe rate-limited for category "
                "%s; serving cache",
                self.category_id,
            )
            return
        except Exception:
            logger.warning(
                "EngagePages freshness probe failed for category %s; "
                "serving possibly-stale cache",
                self.category_id,
                exc_info=True,
            )
            return

        if self.category_last_updated is None:
            self.category_last_updated = most_recent
            return

        if most_recent > self.category_last_updated:
            if self.api.cache is not None:
                # Scoped to this category's engage keys only.
                self.api.cache.invalidate(
                    "engage_by_param", str(self.category_id)
                )
                self.api.cache.invalidate(
                    "engage_by_tag", str(self.category_id)
                )
            self.category_last_updated = most_recent

    def get_index(
        self,
        limit=50,
        offset=0,
        tag_value=None,
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
        self._refresh_if_stale()

        params = {
            "category_id": self.category_id,
            "limit": limit,
            "offset": offset,
            "tag_value": tag_value,
            "key": key,
            "value": value,
            "second_key": second_key,
            "second_value": second_value,
        }

        params = {k: v for k, v in params.items() if v is not None}

        if (
            tag_value
            and isinstance(tag_value, str)
            and not value
            and not second_value
        ):
            list_topics = self.api.get_engage_pages_by_tag(
                category_id=self.category_id,
                limit=limit,
                offset=offset,
                tag=tag_value,
            )
        else:
            list_topics = self.api.get_engage_pages_by_param(**params)

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
        self._refresh_if_stale()
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

    def get_engage_pages_tags(self, value=None):
        """
        Get all tags in {value} engage pages
        for the dropdown filter. If no value is
        passed, it fetches all engage pages tags
        """
        self._refresh_if_stale()
        params = {
            "category_id": self.category_id,
            "limit": -1,
        }
        if value is not None and isinstance(value, str):
            params["key"] = "type"
            params["value"] = value

        list_topics = self.api.get_engage_pages_by_param(**params)
        tags = set()
        for topic in list_topics:
            if topic[6] not in self.exclude_topics:
                try:
                    topics_index = self.parse_topics(topic)
                    if "tags" in topics_index:
                        raw_tags = topics_index["tags"].split(",")
                        cleaned_tags = {
                            tag.strip().lower() for tag in raw_tags
                        }
                        tags.update(cleaned_tags)
                except MetadataError:
                    continue

        return tags

    def parse_active_takeovers(self):
        self._refresh_if_stale()
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
        soup = self._replace_lists(soup)
        soup = self._replace_blockquotes_block(soup)
        soup = self._replace_highlights_block(soup)
        soup = self._replace_image_block(soup)
        soup = self._replace_standard_table_block(soup)
        soup = self._replace_checklist_paragraph(soup)

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
                            if tag_name == "a" and key in URL_METADATA_KEYS:
                                # Remove <a> links
                                value = value[0]["href"]
                            else:
                                value = value[0].string

                        else:
                            value = value[0]
                        if key in URL_METADATA_KEYS:
                            value = normalize_link(value)
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
                        if key in URL_METADATA_KEYS:
                            value = normalize_link(value)
                        metadata[key] = value
                    except Exception as error:
                        error_message = (
                            "Metadata table contains errors:"
                            f" {error} for {topic_path}"
                        )
                        raise MetadataError(error_message)

            if "language" in metadata:
                metadata["language"] = LANGUAGE_MAP.get(
                    str(metadata["language"]).strip().lower(),
                    metadata["language"],
                )

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


class Category:
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
        exclude_topics=[],
    ):
        self.parser = parser
        self.category_id = category_id
        self.exclude_topics = exclude_topics
        self.category_topics = None
        self.index_last_updated = None
        self.category_last_updated = None
        self.category_index_metadata = None
        self.events = None
        pass

    def get_topic(self, path="/"):
        """
        A Flask view function to serve topics from a Discourse category
        """
        if path != "/" and not path.startswith("/"):
            path = "/" + path

        if path == "/":
            topic = self.parser.api.get_topic(self.parser.index_topic_id)
        else:
            try:
                topic_id = self._get_topic_id_from_path(path)
            except PathNotFoundError:
                return flask.abort(404)

            try:
                topic = self.parser.api.get_topic(topic_id)
            except RateLimitedError as rate_error:
                raise ServiceUnavailable(
                    retry_after=rate_error.retry_after
                ) from rate_error
            except HTTPError as http_error:
                return flask.abort(http_error.response.status_code)

        document = self.parser.parse_topic(topic)

        return document

    def get_topic_by_id(self, topic_id):
        """
        A Flask view function to serve a topic by its ID
        """
        try:
            topic = self.parser.api.get_topic(topic_id)
        except RateLimitedError as rate_error:
            raise ServiceUnavailable(
                retry_after=rate_error.retry_after
            ) from rate_error
        except HTTPError as http_error:
            return flask.abort(http_error.response.status_code)

        document = self.parser.parse_topic(topic)

        return document

    def _get_topic_id_from_path(self, path):
        path = path.lstrip("/")
        for topic in self.get_topics_in_category():
            if topic["slug"] == path:
                return topic["id"]
        return None

    def get_category_index_metadata(self, data_name=""):
        """
        Exposes an API to query category metadata.
        Checks if the index topic has been updated or is undefined and
        then fetches/refreshes the metadata

        :param data_name: Name of the data table
        """
        try:
            updated, updated_at = self.parser.api.check_for_topic_updates(
                self.parser.index_topic_id, self.index_last_updated
            )

            if self.category_index_metadata is None or updated:
                self.category_index_metadata = self.parser.parse_index_topic()
                self.index_last_updated = updated_at

        except Exception:
            if self.category_index_metadata is None:
                return None if data_name else {}

        if data_name:
            return self.category_index_metadata.get(data_name)
        else:
            return self.category_index_metadata

    def get_topics_in_category(self):
        """
        Exposes an API to query all topics in a category
        """
        try:
            updated, updated_at = self.parser.api.check_for_category_updates(
                self.category_id, self.category_last_updated
            )

            if self.category_topics is None or updated:
                all_topics = self.parser.api.get_topic_list_by_category(
                    self.category_id
                )
                # Filter out excluded topics
                self.category_topics = [
                    topic
                    for topic in all_topics
                    if topic.get("id") not in self.exclude_topics
                ]
                self.category_last_updated = updated_at

        except Exception:
            if self.category_topics is None:
                # Callers slice and iterate this like the success path
                return []

        return self.category_topics


class Events:
    """
    A class to handle events in a Discourse category.
    It intergrates with the Discourse Events plugin.

    :param parser: A data parser class
    :param category_id: ID of a Discourse category
    """

    def __init__(self, parser, category_id):
        self.parser = parser
        self.category_id = category_id
        self.all_events = None
        self.events_last_updated = None
        self.featured_events = None
        pass

    def get_events(self) -> list:
        """
        Fetches all future events from the target Discourse instance.
        """
        updated, updated_at = self.parser.api.check_for_category_updates(
            self.category_id, self.events_last_updated
        )

        if self.all_events is None or updated:
            self.all_events = self.parser.api.get_events()["events"]
            self.events_last_updated = updated_at

        return self.all_events

    def get_featured_events(self, target_tag="featured-event") -> list:
        """
        Fetches events that are marked with a specific tag.

        :param target_tag: Tag to filter featured events by.
        """
        featured_events_ids = self.parser.api.get_topics_by_tag(target_tag)[
            "grouped_search_result"
        ]["post_ids"]
        all_events = self.get_events()

        self.featured_events = self.parser.parse_featured_events(
            all_events, featured_events_ids
        )

        return self.featured_events


class Articles(BaseParser):
    """
    Blog-style articles built from the Discourse topics carrying a tag,
    whatever their category (e.g. Developer diaries). Only the first
    post of each topic is the article; replies stay on Discourse,
    linked to through each article's forum_url.

    :param api: A DiscourseAPI for retrieving Discourse topics. Prefer
        an anonymous one, so tagged topics in restricted categories are
        never published
    :param tag: The tag marking a topic as an article
    :param url_prefix: URL prefix of the articles on the project
    :param hidden_tags: Tags left out of each article's tags, on top
        of the article tag itself (e.g. "blog", "featured")
    :param exclude_topics: IDs of tagged topics to leave out
    :param words_per_minute: Reading speed used for read_time
    :param max_pages: Cap on the tag listing pages fetched per request
    """

    def __init__(
        self,
        api,
        tag,
        url_prefix,
        hidden_tags=[],
        exclude_topics=[],
        words_per_minute=200,
        max_pages=10,
    ):
        super().__init__(api=api, index_topic_id=None, url_prefix=url_prefix)
        self.tag = tag
        self.hidden_tags = {t.lower() for t in [tag, *hidden_tags]}
        self.exclude_topics = exclude_topics
        self.words_per_minute = words_per_minute
        self.max_pages = max_pages

    def get_index(self, limit=12, offset=0, tags=None):
        """
        A page of articles, newest first

        Args:
        - limit [int]: Number of articles per page
        - offset [int]: Number of articles to skip
        - tags [str | list[str]]: Only keep the articles carrying at
          least one of these tags

        Returns:
        - (articles, total_count): The page of articles and the number
          of articles matching the filter
        """
        topics, users = self._get_tagged_topics()

        tag_filter = {t.lower() for t in _normalise_tags(tags)}
        if tag_filter:
            topics = [
                topic
                for topic in topics
                if tag_filter & {t.lower() for t in self._tag_names(topic)}
            ]

        articles = [
            self._parse_summary(topic, users)
            for topic in topics[offset : offset + limit]
        ]

        return articles, len(topics)

    def get_article(self, slug):
        """
        A single article by its topic slug, or None when no article
        has that slug
        """
        topics, _ = self._get_tagged_topics()
        topic_id = next(
            (topic["id"] for topic in topics if topic["slug"] == slug), None
        )
        if topic_id is None:
            return None

        try:
            topic = self.api.get_topic(topic_id)
        except HTTPError as error:
            # Deleted or made private since the tag listing was cached
            if error.response is not None and error.response.status_code in (
                403,
                404,
                410,
            ):
                return None
            raise

        return self.parse_article(topic)

    def parse_article(self, topic):
        """
        Parse a topic object from the Discourse API into an article:
        the summary fields plus the processed body_html, in-page
        navigation built from its h2/h3 headings, an excerpt and an
        estimated read_time in minutes
        """
        post = topic["post_stream"]["posts"][0]

        soup = BeautifulSoup(post["cooked"], features="html.parser")
        soup = self._process_topic_soup(soup)
        self._replace_lightbox(soup)
        self._replace_lightbox_images(soup)
        navigation = self._parse_headings(soup)

        first_paragraph = soup.find("p")
        excerpt = (
            " ".join(first_paragraph.get_text().split())
            if first_paragraph
            else ""
        )

        likes = next(
            (
                action["count"]
                for action in post.get("actions_summary", [])
                if action.get("id") == 2
            ),
            topic.get("like_count", 0),
        )

        return {
            **self._article_fields(topic),
            "author": self._parse_author(post),
            "likes": likes,
            "updated": dateutil.parser.parse(post["updated_at"]),
            "body_html": str(soup),
            "navigation": navigation,
            "excerpt": excerpt,
            "read_time": self._read_time(soup),
        }

    def _get_tagged_topics(self):
        """
        Every visible topic carrying the tag, newest first, and the
        users the listing references, keyed by user id
        """
        topics = {}
        users = {}

        for page in range(self.max_pages):
            response = self.api.get_topic_list_by_tag(self.tag, page=page)
            topic_list = response.get("topic_list", {})

            for user in response.get("users", []):
                users[user["id"]] = user

            for topic in topic_list.get("topics", []):
                if (
                    topic.get("visible", True)
                    and topic.get("archetype", "regular") == "regular"
                    and topic["id"] not in self.exclude_topics
                ):
                    topics[topic["id"]] = topic

            if not topic_list.get("more_topics_url"):
                break

        return (
            sorted(
                topics.values(),
                key=lambda topic: topic["created_at"],
                reverse=True,
            ),
            users,
        )

    def _parse_summary(self, topic, users):
        """
        Parse a topic from the tag listing into the fields needed for
        an article card
        """
        original_poster = next(
            (
                poster
                for poster in topic.get("posters", [])
                if "Original Poster" in (poster.get("description") or "")
            ),
            None,
        )
        user = (
            users.get(original_poster["user_id"]) if original_poster else None
        )

        return {
            **self._article_fields(topic),
            "author": self._parse_author(user) if user else None,
            "likes": topic.get("op_like_count", topic.get("like_count", 0)),
        }

    def _article_fields(self, topic):
        """
        Fields shared by the listing and the full topic objects
        """
        return {
            "id": topic["id"],
            "title": topic["title"],
            "slug": topic["slug"],
            "path": f"{self.url_prefix}/{topic['slug']}",
            "image": topic.get("image_url"),
            "tags": [
                tag
                for tag in self._tag_names(topic)
                if tag.lower() not in self.hidden_tags
            ],
            "created": dateutil.parser.parse(topic["created_at"]),
            "forum_url": (
                f"{self.api.base_url}/t/{topic['slug']}/{topic['id']}"
            ),
        }

    def _parse_author(self, user):
        """
        Author details from a Discourse user or post object, which both
        carry username, name and avatar_template
        """
        avatar_url = user["avatar_template"].replace("{size}", "96")
        if avatar_url.startswith("/") and not avatar_url.startswith("//"):
            avatar_url = f"{self.api.base_url}{avatar_url}"

        return {
            "name": user.get("name") or user["username"],
            "username": user["username"],
            "avatar_url": avatar_url,
            "url": f"{self.api.base_url}/u/{user['username']}",
        }

    def _replace_lightbox_images(self, soup):
        """
        Turn the images Discourse wraps in a lightbox into Vanilla image
        containers, with shallow spacing below. Keeps the link to the
        full-size image.

        Discourse nests the lightbox <div> in a <p>, which browsers split
        into stray empty paragraphs, so a <p> holding only the image is
        replaced as well.
        """
        for wrapper in soup.select("div.lightbox-wrapper"):
            image = wrapper.find("img")
            if not image:
                continue

            image["class"] = image.get("class", []) + [
                "p-image-container__image"
            ]
            container = soup.new_tag(
                "div", attrs={"class": "p-image-container"}
            )
            container.append(
                (wrapper.find("a", class_="lightbox") or image).extract()
            )
            section = soup.new_tag(
                "div", attrs={"class": "p-section--shallow"}
            )
            section.append(container)

            parent = wrapper.parent
            siblings = [
                child
                for child in parent.contents
                if not (isinstance(child, str) and not child.strip())
            ]
            if parent.name == "p" and siblings == [wrapper]:
                parent.replace_with(section)
            else:
                wrapper.replace_with(section)

        return soup

    def _tag_names(self, topic):
        # Newer Discourse versions return tags as objects
        return [
            tag["name"] if isinstance(tag, dict) else tag
            for tag in topic.get("tags", [])
        ]

    def _parse_headings(self, soup):
        """
        Give every h2 and h3 an id and return them as nested in-page
        navigation items: [{"id", "text", "children": [...]}]
        """
        navigation = []
        used_ids = set()

        for heading in soup.find_all(["h2", "h3"]):
            text = heading.get_text(" ", strip=True)
            if not text:
                continue

            # Reuse the anchor Discourse generates for the heading
            anchor = heading.find("a", attrs={"name": True})
            base_id = heading.get("id") or (
                anchor["name"] if anchor else slugify(text)
            )
            if anchor:
                del anchor["name"]

            heading_id = base_id
            suffix = 2
            while heading_id in used_ids:
                heading_id = f"{base_id}-{suffix}"
                suffix += 1
            used_ids.add(heading_id)
            heading["id"] = heading_id

            item = {"id": heading_id, "text": text, "children": []}
            if heading.name == "h3" and navigation:
                navigation[-1]["children"].append(item)
            else:
                navigation.append(item)

        return navigation

    def _read_time(self, soup):
        """
        Estimated minutes to read the prose, leaving out code blocks
        """
        prose = " ".join(
            text
            for text in soup.find_all(string=True)
            if not text.find_parent("pre")
        )
        words = [
            word
            for word in prose.split()
            if any(character.isalnum() for character in word)
        ]

        return max(1, round(len(words) / self.words_per_minute))
