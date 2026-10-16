"""Render docs/images/social-card.png, the 1280x640 GitHub social preview, with headless Chrome.

usage: CHROME=<path to chrome> python tools/social_card.py
"""

import os
import pathlib
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
CHROME = os.environ.get("CHROME", "google-chrome")

PAGE = """<!doctype html><html><head><meta charset="utf-8"><style>
html,body{margin:0;width:1280px;height:640px;background:#1c2024;color:#eef0ec;
  font-family:'Segoe UI',system-ui,-apple-system,Helvetica,Arial,sans-serif}
.card{box-sizing:border-box;width:1280px;height:640px;padding:88px 96px;display:flex;flex-direction:column}
.mark{height:96px;align-self:flex-start}
h1{font-size:46px;font-weight:600;line-height:1.25;margin:56px 0 0;max-width:1000px}
h1 em{font-style:normal;color:#e3826f}
.stats{display:flex;gap:56px;margin-top:auto;font-size:24px;color:#9aa1a8}
.stats b{display:block;font-family:Consolas,ui-monospace,monospace;font-size:40px;color:#eef0ec}
</style></head><body><div class="card">
<img class="mark" src="WORDMARK">
<h1>Pull request review against your repository's <em>own rules</em>
and the <em>requirements</em> it claims to implement.</h1>
<div class="stats">
  <div><b>30 / 30</b>planted defects found</div>
  <div><b>21 / 21</b>criteria judged right</div>
  <div><b>~$0.03</b>per review</div>
</div>
</div></body></html>"""


def main() -> None:
    wordmark = (ROOT / "docs" / "images" / "wordmark-dark.svg").resolve().as_uri()
    page = pathlib.Path(tempfile.mkdtemp()) / "card.html"
    page.write_text(PAGE.replace("WORDMARK", wordmark), encoding="utf-8")
    target = ROOT / "docs" / "images" / "social-card.png"
    # CHROME comes from the person running this script, not from untrusted input.
    subprocess.run(  # noqa: S603
        [
            CHROME,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--allow-file-access-from-files",
            "--window-size=1280,640",
            f"--screenshot={target}",
            page.as_uri(),
        ],
        check=True,
        capture_output=True,
    )


if __name__ == "__main__":
    main()
