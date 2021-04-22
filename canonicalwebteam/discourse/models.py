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
