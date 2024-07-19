from canonicalwebteam.discourse.exceptions import DataExplorerError


class DiscourseAPI:
    """
    Retrieve information from a Discourse installation
    through its API
    """

    def __init__(
        self,
        base_url,
        session,
        api_key=None,
        api_username=None,
        get_topics_query_id=None,
    ):
        """
        @param base_url: The Discourse URL (e.g. https://discourse.example.com)
        """

        self.base_url = base_url.rstrip("/")
        self.session = session
        self.get_topics_query_id = get_topics_query_id

        if api_key and api_username:
            self.session.headers = {
                "Api-Key": api_key,
                "Api-Username": api_username,
            }

    def __del__(self):
        self.session.close()

    def get_topic(self, topic_id):
        """
        Retrieve topic object by path
        """

        response = self.session.get(f"{self.base_url}/t/{topic_id}.json")
        response.raise_for_status()

        return response.json()

    def get_topics(self, topic_ids):
        """
        This endpoint returns multiple topics HTML cooked content.
        This is possible with the Data Explorer plugin for Discourse
        we are using it to obtain multiple Tutorials content without
        doing multiple API calls.
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
        }

        # Run query on Data Explorer with topic IDs
        topics = ",".join([str(i) for i in topic_ids])

        response = self.session.post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{self.get_topics_query_id}/run",
            headers=headers,
            data={"params": f'{{"topics":"{topics}"}}'},
        )

        result = response.json()

        if "errors" in result and "rows" not in result:
            raise DataExplorerError(
                f'{result["errors"][0]} Have you set the right api_key?'
            )

        pages = result["rows"]
        return pages

    def get_topics_category(self, category_id, page=0):
        response = self.session.get(
            f"{self.base_url}/c/{category_id}.json?page={page}"
        )
        response.raise_for_status()

        return response.json()

    def get_engage_pages_by_param(
        self, category_id, key=None, value=None, limit=50, offset=0
    ):
        """
        Uses data-explorer to query topics with the category
        Engages pages or Takeovers

        Accepts keys and values that are listed in the metadata
        of engage pages or takovers e.g. in the following metadata
        table from /t/nfv-orchestration-for-open-source-telco/25422

        Key	          Value
        image	      https://assets.ubuntu.com/v1/176a11dd.svg
        image_width	  365
        image_height  236
        meta_image
        meta_copydoc  https://docs.google.com/document/d/1M_Oe
        banner_class  dark
        webinar_code  521943
        topic_name	  NFV Orchestration For Open Source Telco
        path	      /engage/nfv-management-and-orchestration
        -charmed-open-source-mano
        type	      webinar
        tags	      osm, gsi, cloud, open source, orchestration

        To get an engage page by path:
        key = path
        value = /engage/nfv-management-and-orchestration-
        charmed-open-source-mano

        Args:
        - limit [int]: 50 by default, also set in data explorer
        - offset [int]: 0 by default (first page)
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
        }
        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=16
        data_explorer_id = 16

        params = (
            {
                "params": (
                    f'{{"category_id":"{category_id}", '
                    f'"limit":"{limit}", "offset":"{offset}"}}'
                )
            },
        )

        if key and value:
            params = (
                {
                    "params": (
                        f'{{"category_id":"{category_id}", '
                        f'"keyword":"{key}", "value":"{value}", '
                        f'"limit":"{limit}", "offset":"{offset}"}}'
                    )
                },
            )

        if limit == -1:
            # Get all engage pages to compile list of tags
            # last resort if you need to get all pages, not performant
            params = ({"params": f'{{"category_id":"{category_id}"}}'},)

        response = self.session.post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{data_explorer_id}/run",
            headers=headers,
            data=params[0],
        )

        response.raise_for_status()
        result = response.json()

        if not result["success"]:
            raise DataExplorerError(response["errors"][0])

        pages = result["rows"]
        return pages

    def get_engage_pages_by_tag(self, category_id, tag, limit=50, offset=0):
        """
        Uses data-explorer to query engage pages

        Same functionality and return values as
        get_engage_pages_by_param, but specifically
        for querying by tags

        Args:
        - limit [int]: 50 by default, also set in data explorer
        - offset [int]: 0 by default (first page)
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
        }
        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=16
        data_explorer_id = 55

        params = (
            {
                "params": (
                    f'{{"category_id":"{category_id}", '
                    f'"tag":"{tag}", '
                    f'"limit":"{limit}", "offset":"{offset}"}}'
                )
            },
        )

        response = self.session.post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{data_explorer_id}/run",
            headers=headers,
            data=params[0],
        )

        response.raise_for_status()
        result = response.json()

        if not result["success"]:
            raise DataExplorerError(response["errors"][0])

        pages = result["rows"]
        return pages
