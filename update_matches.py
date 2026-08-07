import os
import re
import sys

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)

from publisher import (
    get_live_matches_data,
    get_top_match_ticker_html,
    get_modal_matches_html,
)

# Stable insertion markers that publisher.py / rebuilders guarantee are present in
# every rendered index.html. They survive redesigns far better than regexing the
# whole container block (see issue P0-5 in the audit).
TICKER_MARKER = '<div class="top-match-ticker ticker-wrap-css">'
MODAL_MARKER = '<div id="modalMatchList">'


def _replace_between_markers(content: str, start_marker: str, new_inner: str):
    """Replace the inner HTML of the first matched container.

    Uses a non-greedy span bounded on both ends by the container's own closing
    tag. Raises RuntimeError loudly if the marker is absent so a broken template
    fails the workflow step visibly instead of silently no-op'ing.
    """
    start = content.find(start_marker)
    if start == -1:
        raise RuntimeError(
            f"Ticker/modal container marker not found in index.html: {start_marker!r}. "
            "Template changed without updating update_matches.py — refusing to no-op."
        )
    # Find the matching closing </div> for the *outer* wrapper. The ticker wrapper
    # is exactly two nested <div>s; the modal wrapper owns the inner list div.
    # Strategy: locate the content-css inner div and consume through its own close.
    inner_open = content.find('<div class="ticker-content-css">', start)
    if inner_open == -1:
        raise RuntimeError(
            f"Found {start_marker!r} but its inner .ticker-content-css is missing."
        )
    # End of inner div: the FIRST '</div>' after the inner open tag.
    inner_close = content.find("</div>", inner_open)
    if inner_close == -1:
        raise RuntimeError("ticker-content-css has no closing </div> — malformed HTML.")
    outer_close = content.find("</div>", inner_close + len("</div>"))
    if outer_close == -1:
        raise RuntimeError("top-match-ticker wrapper has no closing </div> — malformed HTML.")
    return (
        content[: inner_open + len('<div class="ticker-content-css">')]
        + new_inner
        + content[inner_close:]
    )


def _replace_modal(content: str, new_inner_html: str):
    """Replace the inner list of the match modal."""
    start = content.find(MODAL_MARKER)
    if start == -1:
        raise RuntimeError(
            "Match modal container marker not found: '#modalMatchList'. "
            "Template drifted — refusing to silently no-op."
        )
    open_end = content.find(">", start) + 1
    # The modal list is a single flat div — its direct children are .match-card
    # nodes, so the next top-level '</div>' closes it.
    close = content.find("</div>", open_end)
    if close == -1:
        raise RuntimeError("#modalMatchList has no closing </div> — malformed HTML.")
    return content[:open_end] + "\n" + new_inner_html + content[close:]


def refresh_matches_only():
    if not os.environ.get("FOOTBALL_API_KEY"):
        print("WARNING: FOOTBALL_API_KEY is not set — live match data will be unavailable")

    index_path = os.path.join(PROJECT_DIR, "index.html")
    if not os.path.exists(index_path):
        print("index.html does not exist. Skipping match refresh.")
        return

    print("Fetching today's real matches from API-Football...")
    matches = get_live_matches_data()
    if not matches:
        print("No matches returned or API key unavailable. Skipping index.html match update.")
        return

    ticker_html = get_top_match_ticker_html(matches)
    modal_html = get_modal_matches_html(matches)

    with open(index_path, "r", encoding="utf-8") as f:
        content = f.read()

    original = content
    # If the template placeholders survived into production HTML (shouldn't happen,
    # but guard against a half-rendered template being committed), fill them fast.
    if "{{top_match_ticker_items}}" in content:
        content = content.replace("{{top_match_ticker_items}}", ticker_html)
        content = content.replace("{{modal_matches_html}}", modal_html)
        print("Populated raw template placeholders in index.html.")
    else:
        content = _replace_between_markers(content, TICKER_MARKER, ticker_html)
        # CSS-marquee trick: content is duplicated for seamless looping.
        content = content.replace(ticker_html, ticker_html + ticker_html, 1)
        content = _replace_modal(content, modal_html)

    if content == original:
        raise RuntimeError(
            "update_matches.py produced a no-op — index.html unchanged. "
            "Failing loudly so GitHub Actions flags this run."
        )

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("Successfully updated live match ticker + modal in index.html.")


if __name__ == "__main__":
    refresh_matches_only()
