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

        return response.json()["rows"]

    def get_topics_category(self, category_id, page=0):
        response = self.session.get(
            f"{self.base_url}/c/{category_id}.json?page={page}"
        )
        response.raise_for_status()

        return response.json()

    def engage_pages_by_category(self, category_id=50):
        """
        This endpoint returns engage pages cooked content.
        This is possible with the Data Explorer plugin for Discourse
        we are using it to obtain engage pages by category.

        The id for the data explorer query is always 14

        @params
            - category_id [int]: 50 by default, this is set in the
        https://discourse.ubuntu.com/admin/plugins/explorer?id=14
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
        }
        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=14
        data_explorer_id = 14

        response = self.session.post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{data_explorer_id}/run",
            headers=headers,
            data={"params": f'{{"category_id":"{category_id}"}}'},
        )

        result = response.json()

        if not result["success"]:
            raise DataExplorerError(response["errors"][0])

        pages = result["rows"]
        return pages

    def get_engage_pages_by_param(self, category_id, key, value):
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
        """
        headers = {
            "Accept": "application/json",
            "Content-Type": "multipart/form-data;",
        }
        # See https://discourse.ubuntu.com/admin/plugins/explorer?id=16
        data_explorer_id = 16

        response = self.session.post(
            f"{self.base_url}/admin/plugins/explorer/"
            f"queries/{data_explorer_id}/run",
            headers=headers,
            data={
                "params": (
                    f'{{"category_id": "{category_id}", '
                    f'"keyword": "{key}", "value": "{value}"}}'
                )
            },
        )

        response.raise_for_status()
        result = response.json()

        if not result["success"]:
            raise DataExplorerError(response["errors"][0])

        pages = result["rows"]
        return pages
