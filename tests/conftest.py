import os
import sys

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_app_data(tmp_path_factory):
    previous = os.environ.get("APPDATA")
    os.environ["APPDATA"] = str(tmp_path_factory.mktemp("appdata"))
    yield
    if previous is None:
        os.environ.pop("APPDATA", None)
    else:
        os.environ["APPDATA"] = previous


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)
