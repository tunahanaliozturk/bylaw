import pytest

from bylaw.evidence import is_test


@pytest.mark.parametrize(
    "path",
    [
        "tests/test_app.py",
        "pkg/app_test.go",
        "web/cart.test.ts",
        "web/cart.spec.jsx",
        "Orders.Tests/OrderTests.cs",
        "spec/models/user_spec.rb",
        "app/models/user_spec.rb",
        "__tests__/cart.js",
    ],
)
def test_paths_that_hold_tests_count_as_tests(path: str) -> None:
    assert is_test(path)


@pytest.mark.parametrize(
    "path", ["src/bylaw/testing/helpers.py", "docs/specs/login.md", "app/contest.py", "app/latest.ts"]
)
def test_paths_that_only_mention_testing_do_not(path: str) -> None:
    assert not is_test(path)
