#! /usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name="canonicalwebteam.discourse",
    version="5.0.2",
    author="Canonical webteam",
    author_email="webteam@canonical.com",
    url=(
        "https://github.com/canonical-web-and-design/"
        "canonicalwebteam.discourse"
    ),
    description=(
        "Flask extension to integrate discourse content generated "
        "to docs to your website."
    ),
    packages=find_packages(),
    long_description=open("README.md").read(),
    long_description_content_type="text/markdown",
    install_requires=[
        "Flask>=1.0.2",
        "beautifulsoup4",
        "humanize",
        "python-dateutil",
        "validators",
    ],
    tests_require=[
        "vcrpy-unittest",
        "httpretty",
    ],
)
