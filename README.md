# canonicalwebteam.discourse_docs

Flask extension to integrate discourse content generated to docs to your website.

## Install

Install the project with pip: `pip install canonicalwebteam.discourse_docs`

You can add the extension on your project as follows, replacing, at least, `base_url` and `index_topic_id` with your own settings:

```python
import talisker.requests
from canonicalwebteam.discourse_docs import DiscourseDocs, DiscourseAPI

app = Flask("myapp")
session = talisker.requests.get_session()

discourse_docs = DiscourseDocs(
    parser=DocParser(
        api=DiscourseAPI(
            base_url="https://forum.example.com/", session=session
        ),
        index_topic_id=321,
        url_prefix="/docs",
    ),
    document_template="docs/document.html",
    url_prefix="/docs",
)
discourse_docs.init_app(app)
```

Once this is added you will need to add the file `document.html` to your template folder.

## If you are viewing a protected topic or category, you must provide `api_key` and `api_username`:

```
api_key=fake-api-key
api_username=canonical

discourse_docs = DiscourseDocs(
    parser=DocParser(
        api=DiscourseAPI(
            base_url="https://forum.example.com/",
            session=session,
            api_key=api_key,
            api_username=api_username
        ),
        index_topic_id=321,
        url_prefix="/docs",
    ),
    document_template="docs/document.html",
    url_prefix="/docs",
)
```