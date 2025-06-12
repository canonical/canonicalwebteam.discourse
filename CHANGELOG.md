### 6.4.0 [12-06-2025]
**Updated** Discourse API
- Created a new API to query upcoming events in a category
**Updated** Category class
- Exposes the events API on the Category class

### 6.3.0 [10-06-2025]
**Updated** CategoryParser
- Will split a link found in metadata tables into its href ('url') and text content ('text'), as properties on the table row item.
- Handles tables positioned below the string [details=NAME] and nested in a `<details>` element.
**Updated** test_parser.py
- Added tests for the Category parser

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