import pytest

from tests.fixtures.projects import (
    fixture_a_incomplete_ai_project,
    fixture_b_complete_engineering_project,
)


@pytest.fixture
def project_a():
    """Fixture A: AI project with critically missing information."""
    return fixture_a_incomplete_ai_project()


@pytest.fixture
def project_b():
    """Fixture B: engineering project with a complete evidence chain."""
    return fixture_b_complete_engineering_project()
