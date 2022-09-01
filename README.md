# canonicalwebteam.discourse

Flask extension to integrate discourse content generated to docs to your website. This project was previously named `discourse_docs`.

## Writing documentation

Documentation for how to write documentation pages in Discourse for consumption by this module and how to configure the website to use the module can be found [in the Canonical discourse](https://discourse.canonical.com/t/creating-discourse-based-documentation-pages/159).

Example Flask template for documentation pages can be found in [`examples/document.html`](https://github.com/canonical-web-and-design/canonicalwebteam.discourse/blob/main/examples/document.html)

## Install

Install the project with pip: `pip install canonicalwebteam.discourse`

You can add the extension on your project as follows, replacing, at least, `base_url` and `index_topic_id` with your own settings:

```python
import talisker.requests
from canonicalwebteam.discourse import DiscourseAPI, Tutorials, TutorialParser

app = Flask("myapp")
session = talisker.requests.get_session()

discourse = Tutorials(
    parser=TutorialParser(
        api=DiscourseAPI(
            base_url="https://forum.example.com/", session=session
        ),
        index_topic_id=321,
        url_prefix="/docs",
    ),
    document_template="docs/document.html",
    url_prefix="/docs",
)
discourse.init_app(app)
```

Once this is added you will need to add the file `document.html` to your template folder.

## Local development

For local development, it's best to test this module with one of our website projects like [ubuntu.com](https://github.com/canonical-web-and-design/ubuntu.com/). For more information, follow [this guide (internal only)](https://discourse.canonical.com/t/how-to-run-our-python-modules-for-local-development/308).

## Instructions for Engage pages extension

Because you are viewing a protected topic, you must provide `api_key` and `api_username`. You also need an index topic id, which you can get from discourse.ubuntu.com. Your index topic must contain a metadata section. Visit the EngageParser for more information about the structure. You are encouraged to use an blueprint name that does not collide with existent blueprints. The templates must match the ones provided in the parameters indicated.

Here is an example of an implementation:

```python
engage_pages = EngagePages(
    api=DiscourseAPI(
        base_url="https://discourse.ubuntu.com/",
        session=session,
        get_topics_query_id=14,
        api_key=DISCOURSE_API_KEY, # replace with your API key
        api_username=DISCOURSE_API_USERNAME, # replace with correspoding username
    ),
    category_id=51,
    page_type="engage-pages", # one of ["engage-pages", "takeovers"]
    exclude_topics=[] # this is a list of topic ids that we want to exclude from Markdown error checks
    additional_metadata_validation=[] # list of additional keys in the metadata table that you want to validate existence for e.g. language
)
```

In your project, you need to create your own views:

```python
app.add_url_rule(
    "/engage", view_func=build_engage_index(engage_pages)
)

app.add_url_rule(
    "/engage/<path>", view_func=single_engage_page(engage_pages)
)
```

- Where `build_engage_index` would be your view for the list of engage pages, which you can get by using the method `EngagagePages(args).get_index()`
- While `single_engage_page` would be your single engage pages view, which you can get using `EngagePages(args).get_engage_page(path)`

Similarly for takeovers, you just need to pass `page_type="takeovers"`.

- To get a list of takeovers `EngagePages(args).get_index()` also.
- To get a list of active takeovers `EngagePages(args).parse_active_takeovers()`.