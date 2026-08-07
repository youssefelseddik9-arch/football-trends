"""Fast image refresher: one targeted Wikimedia query per post, retry once
if the result is a duplicate. Aim for ~5-10 seconds total."""
import os
import re
import sys
import glob
import hashlib
import urllib.parse
import random
import requests

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, PROJECT_DIR)
from publisher import GENERATED_IMG_DIR  # noqa: E402

TOPIC_QUERIES = [
    ("Real Madrid", "Real Madrid football"),
    ("Barcelona", "FC Barcelona football"),
    ("Liverpool", "Liverpool FC football"),
    ("Manchester City", "Manchester City FC football"),
    ("Manchester United", "Manchester United Old Trafford"),
    ("Arsenal", "Arsenal FC football"),
    ("Chelsea", "Chelsea FC football"),
    ("Tottenham", "Tottenham Hotspur football"),
    ("Newcastle", "Newcastle United football"),
    ("Bayern", "Bayern Munich football"),
    ("Dortmund", "Borussia Dortmund football"),
    ("Paris", "Paris Saint-Germain football"),
    ("Juventus", "Juventus FC football"),
    ("AC Milan", "AC Milan football"),
    ("Inter", "Inter Milan football"),
    ("Atletico", "Atletico Madrid football"),
    ("Al-Hilal", "Al-Hilal SFC Saudi"),
    ("Al-Nassr", "Al-Nassr FC Saudi"),
    ("Hilal", "Al-Hilal Saudi football"),
    ("Nassr", "Al-Nassr Saudi football"),
    ("Saudi", "Saudi Pro League football"),
    ("Champions League", "UEFA Champions League football"),
    ("Premier League", "Premier League football"),
    ("Copa del Rey", "Copa del Rey football"),
    ("Bellingham", "Jude Bellingham"),
    ("Mbappe", "Kylian Mbappe"),
    ("Messi", "Lionel Messi football"),
    ("Ronaldo", "Cristiano Ronaldo football"),
    ("Salah", "Mohamed Salah"),
    ("Haaland", "Erling Haaland"),
    ("Saka", "Bukayo Saka"),
    ("Vinicius", "Vinicius Junior Real Madrid"),
    ("Rodri", "Rodri Manchester City"),
    ("Yamal", "Lamine Yamal"),
    ("Kane", "Harry Kane Bayern"),
    ("Spain", "Spain national football team"),
    ("Egypt", "Egypt national football team"),
    ("Morocco", "Morocco national football team"),
    ("Saudi Arabia", "Saudi Arabia football team"),
    ("transfer", "Football transfer press conference"),
    ("injury", "Football injury"),
    ("coach", "Football coach"),
    ("manager", "Football manager"),
    ("win", "Football celebration"),
    ("signing", "Football shirt unveil"),
]


def pick_query(title):
    t = title.lower()
    for marker, query in TOPIC_QUERIES:
        if marker.lower() in t:
            return query
    return "Football match stadium"


def search_and_pick(query, used_hashes, timeout=8):
    url = (
        "https://commons.wikimedia.org/w/api.php?action=query&format=json"
        "&prop=imageinfo&iiprop=url&iiurlwidth=900"
        "&generator=search&gsrnamespace=6"
        "&gsrsearch={q}&gsrlimit=15"
    ).format(q=urllib.parse.quote(query))
    try:
        r = requests.get(url, timeout=timeout,
                         headers={"User-Agent": "GoalPulse/1.0 (editorial)"})
        if r.status_code != 200:
            return None
        pages = list(r.json().get("query", {}).get("pages", {}).values())
        random.shuffle(pages)
        for p in pages:
            ii = p.get("imageinfo", [{}])[0]
            u = ii.get("thumburl") or ii.get("url")
            if not u:
                continue
            if not u.lower().split("?", 1)[0].endswith((".jpg", ".jpeg", ".png")):
                continue
            try:
                rr = requests.get(u, timeout=15,
                                  headers={"User-Agent": "GoalPulse/1.0 (editorial)"})
                if rr.status_code != 200 or len(rr.content) < 6000:
                    continue
                h = hashlib.md5(rr.content).hexdigest()
                if h in used_hashes:
                    continue
                return (rr.content, h, u)
            except Exception:
                continue
    except Exception as e:
        print(f"  ! search error for {query!r}: {e}")
    return None


def fetch_image(title, slug, used_hashes):
    primary = pick_query(title)
    result = search_and_pick(primary, used_hashes)
    if result:
        return primary, result
    # Fallback: try a generic football query
    return "Football match stadium", search_and_pick("Football match stadium", used_hashes)


def replace_image_paths(content, old_img, new_img):
    if old_img == new_img:
        return content
    out = content
    for needle in [
        f'<meta property="og:image" content="{old_img}"',
        f'<meta name="twitter:image" content="{old_img}"',
    ]:
        out = out.replace(needle, needle.replace(old_img, new_img))
    out = re.sub(r'(class="hero-img"[^>]*?\s)src="' + re.escape(old_img) + r'"',
                  r'\1src="' + new_img + r'"', out, count=1)
    if f'class="hero-img"' in out and f'src="{new_img}"' not in out:
        out = re.sub(r'src="' + re.escape(old_img) + r'"([^>]*?class="hero-img")',
                      'src="' + new_img + r'"\1', out, count=1)
    out = re.sub(r'("image":\s*\[\s*")' + re.escape(old_img) + r'("\s*\])',
                  r'\1' + new_img + r'\2', out, count=1)
    return out


def main(force=False):
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
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            continue
        m_t = re.search(r"<title>(.*?)\|", content)
        title = m_t.group(1).strip() if m_t else None
        if not title:
            skipped += 1
            continue
        cache_path = os.path.join(GENERATED_IMG_DIR, f"post_{slug}.jpg")

        if os.path.exists(cache_path) and not force:
            try:
                h = hashlib.md5(open(cache_path, "rb").read()).hexdigest()
                used_hashes[h] = slug
            except Exception:
                pass
            skipped += 1
            continue

        query, result = fetch_image(title, slug, used_hashes)
        if not result:
            print(f"  ! {filename}: no unique image (query={query!r})")
            skipped += 1
            continue
        blob, h, src_url = result
        with open(cache_path, "wb") as f:
            f.write(blob)
        used_hashes[h] = slug
        new_img = f"images/generated/post_{slug}.jpg"

        m_old = re.search(r'class="hero-img"[^>]*?\ssrc="([^"]+)"', content)
        if not m_old:
            m_old = re.search(r'src="([^"]+)"[^>]*?class="hero-img"', content)
        old_img = m_old.group(1) if m_old else None
        new_content = content
        if old_img and old_img != new_img:
            new_content = replace_image_paths(content, old_img, new_img)
        if new_content != content:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(new_content)
        updated += 1
        print(f"  ok {filename} ({query[:30]})")
    print(f"\nDone. updated={updated} skipped={skipped} unique_images={len(used_hashes)}")


if __name__ == "__main__":
    main(force=True)
