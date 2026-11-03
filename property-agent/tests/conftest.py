from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def pytest_addoption(parser):
    parser.addoption("--live", action="store_true", help="also run tests that call the real King County site")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="needs --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8", errors="ignore")


@pytest.fixture
def seattle_detail_html() -> str:
    return load_fixture("kc_detail_9331800500.html")


@pytest.fixture
def bellevue_detail_html() -> str:
    return load_fixture("kc_detail_8146100590.html")


@pytest.fixture
def notfound_detail_html() -> str:
    return load_fixture("kc_detail_notfound.html")


@pytest.fixture
def seattle_dashboard_html() -> str:
    return load_fixture("kc_dashboard_9331800500.html")
