# canonicalwebteam.discourse_docs

Flask extension to integrate discourse content generated to docs to your website.

## Install

Install the project with pip: `pip install canonicalwebteam.discourse_docs`

You can add the extension on your project:

```
from canonicalwebteam.discourse_docs import DiscourseDocs, DiscourseAPI

discourse_api = DiscourseAPI(
    base_url="https://forum.snapcraft.io/",
    frontpage_id=3781,  # The "Snap Documentation" topic
    category_id=15,  # The "doc" category
)

# From constructor
DiscourseDocs(
    app=app,
    model=discourse_api,
    url_prefix="/",
    document_template="document.html",
)

# or from init_app
discourse_docs = DiscourseDocs()
discourse_docs.init_app(
    app=app,
    model=discourse_api,
    url_prefix="/",
    document_template="document.html",
)
```

Once this is added you will need to add the file `document.html` to your template folder.
