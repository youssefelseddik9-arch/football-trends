"""Backfill unique images for existing articles via Wikimedia Commons (no key required).
Updates every occurrence of the hero image URL inside each post_*.html file."""
import os
import re
import sys
import glob

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publisher import fetch_wikimedia_image, detect_title_language, GENERATED_IMG_DIR

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

IMAGE_FIELDS = [
    ('<meta property="og:image" content="', '"'),
    ('<meta name="twitter:image" content="', '"'),
    ('<img src="', '" class="hero-img"'),
    ('"image": ["', '"]'),
]


def backfill(limit=None, force=False):
    files = sorted(glob.glob(os.path.join(PROJECT_DIR, "post_*.html")), reverse=True)
    if limit:
        files = files[:limit]
    updated = 0
    for fpath in files:
        filename = os.path.basename(fpath)
        m = re.search(r'post_(\d{14})\.html', filename)
        if not m:
            continue
        slug = m.group(1)
        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        m_title = re.search(r'<title>(.*?)\|', content)
        if not m_title:
            continue
        title = m_title.group(1).strip()
        m_img = re.search(r'class="hero-img"[^>]*?\ssrc="(.*?)"', content)
        if not m_img:
            m_img = re.search(r'src="(.*?)"[^>]*?class="hero-img"', content)
        old_img = m_img.group(1) if m_img else "images/hero.webp"
        is_generic = old_img in ("images/hero.webp", "images/world-cup-trophy.webp",
                                  "images/press-conference.webp", "images/celebration-contrast.webp",
                                  "images/walking-away.webp")
        if not force and not is_generic:
            continue
        new_img, _attr = fetch_wikimedia_image(title, slug)
        if not new_img or new_img == old_img:
            continue
        # Replace all occurrences of the old image path with the new one.
        # We target only occurrences that exactly match the old hero image path to avoid
        # clobbering logo/other assets on the page.
        new_content = content.replace(old_img, new_img)
        if new_content == content:
            continue
        with open(fpath, "w", encoding="utf-8") as f:
            f.write(new_content)
        updated += 1
        print(f"Backfilled {filename}: {old_img} -> {new_img}")
    print(f"Backfill complete. {updated} article(s) updated.")


if __name__ == "__main__":
    limit = None
    force = False
    args = sys.argv[1:]
    if "--limit" in args:
        i = args.index("--limit")
        limit = int(args[i + 1])
    if "--force" in args:
        force = True
    backfill(limit=limit, force=force)
