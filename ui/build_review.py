"""Build the standalone review page served by all HMU versions."""
from pathlib import Path


def render_review():
    ui = Path(__file__).resolve().parent
    template = (ui / "review.html").read_text(encoding="utf-8")
    css = (ui / "review.css").read_text(encoding="utf-8")
    js = (ui / "review.js").read_text(encoding="utf-8")
    return template.replace("<!-- REVIEW_CSS -->", f"<style>\n{css}</style>").replace(
        "<!-- REVIEW_JS -->", f"<script>\n{js}</script>"
    )


if __name__ == "__main__":
    output = Path(__file__).resolve().parents[1] / "review.html"
    pending = output.with_suffix(".html.pending")
    pending.write_text(render_review(), encoding="utf-8")
    pending.replace(output)
