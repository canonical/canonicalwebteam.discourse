#! /usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name="canonicalwebteam.discourse",
    version="0.1",
    author="Canonical webteam",
    author_email="webteam@canonical.com",
    url="https://github.com/canonical-webteam/canonicalwebteam.docs",
    description=(
        "Flask extension to integrate discourse content generated "
        "to docs to your website."
    ),
    packages=find_packages(),
    long_description=open("README.md").read(),
    install_requires=[
        "Flask==1.0.2",
        "canonicalwebteam.http==0.1.6",
        "requests-cache==0.4.13",
        "yamlordereddictloader==0.4.0",
        "beautifulsoup4==4.7.1",
        "humanize==0.5.1",
        "python-dateutil==2.7.5",
    ],
    tests_require=["responses==0.10.5", "requests-mock==1.5.2"],
)
