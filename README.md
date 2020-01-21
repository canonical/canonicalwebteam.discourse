# canonicalwebteam.discourse_docs

Flask extension to integrate discourse content generated to docs to your website.

## Install

Install the project with pip: `pip install canonicalwebteam.discourse_docs`

You can add the extension on your project:

```
from canonicalwebteam.discourse_docs import DiscourseDocs, DiscourseAPI

app = Flask("myapp")

DISCOURSE_BASE_URL = "https://forum.example.com/"
DOCS_INDEX_TOPIC = 321
DOCS_CATEGORY_ID = 21
DOCS_URL_PREFIX = '/docs'
DOCS_TEMPLATE_PATH = "docs/document.html"

discourse_api = DiscourseAPI(
    base_url=DISCOURSE_BASE_URL
)

discourse_parser = DocParser(
    discourse_api,
    DOCS_CATEGORY_ID,
    discourse_index_id,
    url_prefix
)

DiscourseDocs(
    parser=discourse_parser,
    index_topic_id=DOCS_INDEX_TOPIC,
    document_template=DOCS_TEMPLATE_PATH,  # Optional
    url_prefix=DOCS_URL_PREFIX,  # Optional
).init_app(app)
```

Once this is added you will need to add the file `document.html` to your template folder.
