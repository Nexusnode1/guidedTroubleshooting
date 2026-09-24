"""Shared fixtures built from the official data files."""

import pytest

from app.services.catalog import load_catalog, load_siis_rows


@pytest.fixture(scope="session")
def catalog():
    return load_catalog()


@pytest.fixture(scope="session")
def catalog_by_id(catalog):
    return {entry["id"]: entry for entry in catalog}


@pytest.fixture(scope="session")
def siis_rows():
    return load_siis_rows()
