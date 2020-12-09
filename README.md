# canonicalwebteam.discourse

Flask extension to integrate discourse content generated to docs to your website. This project was previously named `discourse_docs`.

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

## Instructions for Engage pages extension

Because you are viewing a protected topic, you must provide `api_key` and `api_username`. You also need an index topic id, which you can get from discourse.ubuntu.com. Your index topic must contain a metadata section. Visit the EngageParser for more information about the structure. You are encouraged to use an blueprint name that does not collide with existent blueprints. The templates must match the ones provided in the parameters indicated.

Here is an example of an implementation:

```python
engage_path = "/engage"
engage_docs = EngagePages(
    parser=EngageParser(
        api=DiscourseAPI(
            base_url="https://discourse.ubuntu.com/",
            session=session,
            api_key="secretkey", # API KEY used in the tests
            api_username="canonical",
        ),
        index_topic_id=17229,
        url_prefix=engage_path,
    ),
    document_template="/engage/base.html",
    url_prefix=engage_path,
    blueprint_name="engage-pages",
)
```

Additionally, if you need a list of all engage pages, you would construct a view this way:

```python
app.add_url_rule(
    engage_path, view_func=build_engage_index(engage_docs)
)
```

Where `build_engage_index` would be your view.
