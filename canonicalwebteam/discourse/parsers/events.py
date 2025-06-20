class EventsParser:
    """
    Parses featured events from a list of all events.
    """

    def __init__(self, api):
        self.api = api

    def parse_featured_events(self, all_events, featured_events_ids) -> list:
        """
        Sorts through all events and returns only those that are featured.

        :return: List of events objects that are featured events
        """
        featured_events_ids = set(featured_events_ids)
        featured_events = []

        for event in all_events:
            if event["id"] in featured_events_ids:
                featured_events.append(event)

        return featured_events
