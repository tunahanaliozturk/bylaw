"""Capture the README screenshots from real bylaw comments on the public bylaw-demo repository.

usage: uv run --with playwright python tools/screenshots.py
Uses the installed Google Chrome, so no browser download is needed. Writes light and dark PNGs to
docs/images/.
"""

import pathlib

from playwright.sync_api import sync_playwright

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "images"
PULL = "https://github.com/tunahanaliozturk/bylaw-demo/pull/7"

# (file name, element on the pull request page) for bylaw's own comments on demo pull request 7.
SHOTS = [
    ("screenshot-inline", "#discussion_r4297442598"),
    ("screenshot-summary", "#issuecomment-6221096826"),
]


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome")
        for scheme in ("light", "dark"):
            page = browser.new_page(
                viewport={"width": 1100, "height": 900}, color_scheme=scheme, device_scale_factor=2
            )
            page.goto(PULL, wait_until="networkidle")
            for name, selector in SHOTS:
                element = page.locator(selector).first
                element.scroll_into_view_if_needed()
                element.screenshot(path=str(OUT / f"{name}-{scheme}.png"))
            page.close()
        browser.close()


if __name__ == "__main__":
    main()
