### 7.1.0 [18-06-2025]
**Updated** Category class
- The function `get_topics_in_category` now returns an array of objects

### 7.0.0 [18-06-2025]
**Added** Events class
- Created a new class to handle events from 'Discourse Calender (and events)' API
**Added** EventsParser class
- Created a new parser to process the events retrieve by the Events class
**Updated** check_for_category_updates & check_for_topic_updates
- Moved from Category into DiscourseAPI 

### 6.5.0 [12-06-2025]
**Updated** Discourse API
- Created a new API to query upcoming events in a category
**Updated** Category class
- Exposes the events API on the Category class

### 6.4.0 [10-06-2025]
**Updated** CategoryParser
- Will split a link found in metadata tables into its href ('url') and text content ('text'), as properties on the table row item.
- Handles tables positioned below the string [details=NAME] and nested in a `<details>` element.
**Updated** test_parser.py
- Added tests for the Category parser

### 6.3.0 [02-07-2025]
**Updated** EngagePages class
- Remove duplicated tags from the list of tags returned from `get_engage_pages_tags`

### 6.2.0 [28-04-2025]
**Added** _inject_custom_css def
- A function that finds css directives (`[style=CLASSNAME]`) in the soup and applies to them to the next found element.

### 6.1.1 [12-03-2025]
**Updated** EngagePages class
- Pass values for the provided keys, even if the values are empty or null, as they can be a filter themselves.

### 6.1.0 [25-01-2025]
**Updated** Category class
- Check for additions or deletions of topics within a category and update cached data if needed

### 6.0.0 [28-01-2025]
**Updated** Category class 
- Removed to template handling from within the Category class.
- Bump to 6.0.0, as the previous update was a major

### 5.8.0 [28-01-2025]
**Added** Category class 
- A generic class for processing discourse categories and the topics they contain
