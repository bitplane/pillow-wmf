from pathlib import Path

import pytest


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    compatibility_root = Path(__file__).parent.resolve()
    for item in items:
        if item.path.is_relative_to(compatibility_root):
            item.add_marker(pytest.mark.compatibility)
