"""The app manifest asks GitHub for exactly what the server uses, and the registration page sends it."""

import json
import re
from pathlib import Path

from bylaw.app.auth import DEFAULTS_PERMISSIONS, REVIEW_PERMISSIONS
from bylaw.app.webhook import REVIEW_ACTIONS

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = json.loads((ROOT / "docs" / "app" / "manifest.json").read_text(encoding="utf-8"))


def test_the_manifest_asks_for_the_permissions_the_tokens_use_and_no_more() -> None:
    assert MANIFEST["default_permissions"] == REVIEW_PERMISSIONS | DEFAULTS_PERMISSIONS


def test_the_manifest_subscribes_to_pull_request_events_only() -> None:
    assert MANIFEST["default_events"] == ["pull_request"]
    assert {"opened", "synchronize", "reopened", "ready_for_review"} == REVIEW_ACTIONS


def test_the_app_is_private_to_the_account_that_registers_it() -> None:
    assert MANIFEST["public"] is False


def test_the_registration_page_sends_the_same_manifest() -> None:
    page = (ROOT / "docs" / "app" / "register.html").read_text(encoding="utf-8")
    embedded = re.search(r'<script type="application/json" id="manifest">(.*?)</script>', page, re.DOTALL)

    assert embedded is not None
    assert json.loads(embedded.group(1)) == MANIFEST
