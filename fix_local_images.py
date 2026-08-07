"""Replace stale or duplicated images across every post_*.html. Pulls a fresh
image via Wikimedia Commons for every post, compares it against already-used
hashes, retries up to N times when the API returns a duplicate, and rewrites
the article to point at the new image."""
import os
import re
import sys
import glob
import hashlib
import urllib.parse
import random
import requests

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from publisher import fetch_wikimedia_image, detect_title_language, GENERATED_IMG_DIR

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

LOCAL_IMG_BASENAMES = {
    "images/hero.webp", "images/world-cup-trophy.webp",
    "images/celebration-contrast.webp", "images/celebration-contrast-mobile.webp",
    "images/press-conference.webp", "images/press-conference-mobile.webp",
    "images/walking-away.webp", "images/walking-away-mobile.webp",
    "images/world-cup-trophy-mobile.webp",
}

WIKIMEDIA_API = (
    "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
    "&iiprop=url|extmetadata&iiurlwidth=900&generator=search&gsrnamespace=6"
    "&gsrsearch={q}&gsrlimit=30"
)


def fetch_distinct(title, slug, used_hashes, max_attempts=6):
    """Try several distinct Wikimedia queries to get a fresh, non-duplicate image."""
    entity_queries = [
        "association football", "football match stadium",
        "football player action", "football fans stadium",
        "soccer training pitch", "football trophy ceremony",
    ]
    t_lower = title.lower()
    for term in [
        "Real Madrid", "FC Barcelona", "Liverpool F.C.", "Manchester City F.C.",
        "Arsenal F.C.", "FC Bayern Munich", "Paris Saint-Germain",
        "Al-Hilal SFC", "Al-Nassr FC", "Lionel Messi", "Cristiano Ronaldo",
        "Kylian Mbappé", "Jude Bellingham", "Saudi Pro League",
        "UEFA Champions League",
    ]:
        if term.lower() in t_lower:
            entity_queries.insert(0, term)
            break

    random.shuffle(entity_queries)
    attempts = 0
    while attempts < max_attempts and entity_queries:
        q = entity_queries.pop(0)
        try:
            url = WIKIMEDIA_API.format(q=urllib.parse.quote(q))
            r = requests.get(url, timeout=12,
                             headers={"User-Agent": "GoalPulse/1.0 (editorial)"})
            if r.status_code != 200:
                attempts += 1
                continue
            pages = list(r.json().get("query", {}).get("pages", {}).values())
            random.shuffle(pages)
            for p in pages:
                ii = p.get("imageinfo", [{}])[0]
                img_url = ii.get("thumburl") or ii.get("url")
                if not img_url:
                    continue
                if not img_url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg", ".png")):
                    continue
                resp = requests.get(img_url, timeout=20,
                                    headers={"User-Agent": "GoalPulse/1.0 (editorial)"})
                if resp.status_code != 200 or len(resp.content) < 6000:
                    continue
                h = hashlib.md5(resp.content).hexdigest()
                if h in used_hashes:
                    continue
                return (resp.content, h)
        except Exception as e:
            print(f"  ! wiki error: {e}")
        attempts += 1
    return None


def extract_title(path):
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()
    m = re.search(r"<title>(.*?)\|", content)
    return m.group(1).strip() if m else None


def extract_current_img(content):
    m = re.search(r'class="hero-img"[^>]*?\ssrc="(.*?)"', content)
    if not m:
        m = re.search(r'src="(.*?)"[^>]*?class="hero-img"', content)
    return m.group(1) if m else None


def fix():
    files = sorted(glob.glob(os.path.join(PROJECT_DIR, "post_*.html")), reverse=True)
    used_hashes = {}
    updated = 0
    skipped = 0

    for fpath in files:
        filename = os.path.basename(fpath)
        m = re.search(r"post_(\d{14})\.html", filename)
        if not m:
            continue
        slug = m.group(1)
        title = extract_title(fpath)
        if not title:
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            content = f.read()
        current = extract_current_img(content)
        needs_fix = (current in LOCAL_IMG_BASENAMES
                     or current is None
                     or (current and current.startswith("images/generated/")
                         and not os.path.exists(os.path.join(PROJECT_DIR, current))))

        if not needs_fix:
            skipped += 1
            continue

        cache_path = os.path.join(GENERATED_IMG_DIR, f"post_{slug}.jpg")
        if os.path.exists(cache_path):
            try:
                used_hashes[hashlib.md5(open(cache_path, "rb").read()).hexdigest()] = True
            except Exception:
                pass

        result = fetch_distinct(title, slug, used_hashes)
        if not result:
            print(f"  ! {filename}: no distinct image available, leaving as-is")
            continue
        blob, h = result
        with open(cache_path, "wb") as f:
            f.write(blob)
        new_img = f"images/generated/post_{slug}.jpg"
        used_hashes[h] = True

        new_content = content
        for placeholder in [
            '<meta property="og:image" content="{}"',
            '<meta name="twitter:image" content="{}"',
        ]:
            for occ in re.findall(re.escape(placeholder).replace(r"\{\}", r'([^"]+)'), new_content):
                new_content = new_content.replace(occ, new_img, 1)
        m_img_old = re.search(r'(class="hero-img"[^>]*?\s)src="[^"]*"', new_content)
        if not m_img_old:
            m_img_old = re.search(r'(src=")[^"]*("[^>]*?class="hero-img")', new_content)
        if m_img_old:
            new_content = re.sub(r'(class="hero-img"[^>]*?\s)src="[^"]*"',
                                  r'\1src="' + new_img + '"', new_content, count=1)
        else:
            new_content = re.sub(r'src="[^"]*"([^>]*?class="hero-img")',
                                  'src="' + new_img + r'"\1', new_content, count=1)
        # JSON-LD image list
        new_content = re.sub(r'("image":\s*\[\s*")[^"]*("\])',
                              r'\1' + new_img + r'\2', new_content, count=1)

        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
            updated += 1
            print(f"  ok  {filename}: {current} -> {new_img}")
        else:
            skipped += 1

    print(f"\nDone. Updated={updated} Skipped={skipped} FilesScanned={len(files)}")
    print(f"Unique image hashes: {len(used_hashes)}")


if __name__ == "__main__":
    fix()
