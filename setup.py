#!/usr/bin/env python3

from setuptools import setup, find_packages

setup(
    name="pybank",
    version="0.1.0",
    description="Download and convert bank statements",
    author="thowi",
    author_email="thomas@wittek.me",
    url="https://github.com/thowi/pybank",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "pydantic",
        "chardet",
        "selenium",
    ],
    extras_require={
        "dev": [
            "pytest",
        ],
    },
)
