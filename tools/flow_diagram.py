"""Render the README review-flow diagram to docs/images/flow-{light,dark}.png with headless Chrome.

usage: CHROME=<path to chrome> python tools/flow_diagram.py
"""

import os
import pathlib
import subprocess
import tempfile

OUT = pathlib.Path(__file__).resolve().parents[1] / "docs" / "images"
CHROME = os.environ.get("CHROME", "google-chrome")
W, H = 1020, 250

THEMES = {
    "light": {
        "ink": "#1c2024",
        "muted": "#5b6168",
        "line": "#c9cdc6",
        "fill": "#f6f7f4",
        "accent": "#a33a2c",
    },
    "dark": {"ink": "#eef0ec", "muted": "#9aa1a8", "line": "#3d434a", "fill": "#161b22", "accent": "#e3826f"},
}

# (x, y, w, h, title, lines, badge, emphasised)
BOXES = [
    (
        170,
        62,
        190,
        126,
        "Context",
        ["diff of the change", "rules from the base branch", "linked issues and specs"],
        "1",
        False,
    ),
    (400, 15, 190, 100, "Checks", [".editorconfig rules", "no model needed"], "", False),
    (400, 135, 190, 100, "Reviewer", ["your model key, or", "Claude Code / Codex"], "2", False),
    (630, 75, 170, 100, "Validate", ["only changed lines", "only real citations"], "3", False),
    (840, 75, 170, 100, "Post", ["inline comments", "summary + checklist"], "4", True),
]

ARROWS = [
    "M130 125 H164",
    "M360 125 H380 V65 H394",
    "M360 125 H380 V185 H394",
    "M590 65 H610 V125 H624",
    "M590 185 H610 V125 H624",
    "M800 125 H834",
]

MONO = "'JetBrains Mono', Consolas, ui-monospace, monospace"
SANS = "'Segoe UI', system-ui, -apple-system, Helvetica, Arial, sans-serif"


def svg(t: dict[str, str]) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">',
        "<defs>",
        '<marker id="head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        'orient="auto">'
        f'<path d="M0 0 L10 5 L0 10 z" fill="{t["muted"]}"/></marker>',
        "</defs>",
        f'<rect x="10" y="105" width="120" height="40" rx="20" fill="{t["fill"]}" stroke="{t["ink"]}" '
        'stroke-width="1.6"/>',
        f'<text x="70" y="130" text-anchor="middle" font-family="{SANS}" font-size="14" font-weight="600" '
        f'fill="{t["ink"]}">Pull request</text>',
    ]
    for d in ARROWS:
        parts.append(
            f'<path d="{d}" fill="none" stroke="{t["muted"]}" stroke-width="1.6" marker-end="url(#head)"/>'
        )
    for x, y, w, h, title, lines, badge, strong in BOXES:
        stroke = t["accent"] if strong else t["line"]
        parts.append(
            f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="10" fill="{t["fill"]}" stroke="{stroke}" '
            f'stroke-width="{1.8 if strong else 1.4}"/>'
        )
        parts.append(
            f'<text x="{x + 16}" y="{y + 30}" font-family="{MONO}" font-size="16" font-weight="700" '
            f'fill="{t["ink"]}">{title}</text>'
        )
        if badge:
            parts.append(f'<circle cx="{x + w - 20}" cy="{y + 24}" r="10" fill="{t["accent"]}"/>')
            parts.append(
                f'<text x="{x + w - 20}" y="{y + 28.5}" text-anchor="middle" font-family="{SANS}" '
                f'font-size="12" font-weight="700" fill="#ffffff">{badge}</text>'
            )
        for i, line in enumerate(lines):
            parts.append(
                f'<text x="{x + 16}" y="{y + 56 + i * 22}" font-family="{SANS}" font-size="13.5" '
                f'fill="{t["muted"]}">{line}</text>'
            )
    parts.append("</svg>")
    return "".join(parts)


for name, theme in THEMES.items():
    page = pathlib.Path(tempfile.mkdtemp()) / f"flow-{name}.html"
    page.write_text(
        '<!doctype html><html><head><meta charset="utf-8">'
        "<style>html,body{margin:0;background:transparent}svg{display:block}</style>"
        f"</head><body>{svg(theme)}</body></html>",
        encoding="utf-8",
    )
    target = OUT / f"flow-{name}.png"
    # CHROME comes from the person running this script, not from untrusted input.
    subprocess.run(  # noqa: S603
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--force-device-scale-factor=2",
            f"--window-size={W},{H}",
            "--default-background-color=00000000",
            f"--screenshot={target}",
            page.resolve().as_uri(),
        ],
        check=True,
        capture_output=True,
    )
