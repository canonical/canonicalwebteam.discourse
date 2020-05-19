# canonicalwebteam.discourse_docs

Flask extension to integrate discourse content generated to docs to your website.

## Install

Install the project with pip: `pip install canonicalwebteam.discourse_docs`

You can add the extension on your project:

``` python
from canonicalwebteam.discourse_docs import DiscourseDocs, DiscourseAPI

app = Flask("myapp")

DISCOURSE_BASE_URL = "https://forum.example.com/"
DOCS_INDEX_TOPIC = 321
DOCS_CATEGORY_ID = 21 # Optionnal in case need to limit to a category
DOCS_URL_PREFIX = '/docs'
DOCS_TEMPLATE_PATH = "docs/document.html"

discourse_api = DiscourseAPI(
    base_url=DISCOURSE_BASE_URL
)

discourse_parser = DocParser(
    api=discourse_api,
    category_id=DOCS_CATEGORY_ID,
    index_topic_id=DOCS_INDEX_TOPIC,
    url_prefix=DOCS_URL_PREFIX,
)

discourse_docs = DiscourseDocs(
    parser=discourse_parser,
    document_template=DOCS_TEMPLATE_PATH,  # Optional
    url_prefix=DOCS_URL_PREFIX,  # Optional
    blueprint_name=discourse_docs, # Optional
)

discourse_docs.init_app(app)
```

Once this is added you will need to add the file `document.html` to your template folder.
