# Documentation layout for Discourse docs

## Full-width documentation layout

Vanilla 4.5.0 introduced a new full-width documentation layout. This layout is recommended for all new documentation sites.

### Requirements

To use new documentation layout you need to use Vanilla 4.5.0 or newer and Discourse 2.7.0 or newer (to have a support for automatically generated table of contents).

### Layout

Please familarise yourself with [the Vanilla documentation about the documentation layout](https://vanillaframework.io/docs/layouts/documentation) to have a better understanding of the structure.

### Template for Discourse docs

Example template for documentation pages can be found in [`examples/document.html`](document.html).

This template needs to extend a base layout template of the project and replace the whole contents of the `<body>` element, because top navigation and footer need to be adjusted to new layout as well.

It's recommended to have partial templates for header and footer and include them in the brochure layout template and in the documentation template. In our example the `is_docs`` template variable is used to differentiate between docs and other pages in partials so that they can render differently.

#### Customisation

There are several elements that can or need to be customised when applying the template to your project.

- name of the base layout template that is being extended
- contents of `{% block title %}` need to be adjusted
- names and contents of partial templates for header and footer
- adjust `expandable` parameter to `create_navigation` if expandable navigation is needed

There may be other changes needed based on the project-specific needs.

#### Example usage

The new documentation layout is already used on [microk8s.io](https://microk8s.io/docs). You can refer to the pull request [canonical/mikrok8s.io#624](https://github.com/canonical/microk8s.io/pull/624/files) that introduced the new layout for an example of how to use it.

## Old brochure site documentation layout

For an example template of the old brochure site documentation layout, see [`examples/document-brochure.html`](document-brochure.html).

Please note that the use of this old template is not recommended on new sites. Please use the official full-width documentation layout described above if possible.



