import os
import feedparser
import urllib.parse
from datetime import datetime, timedelta
import requests
import json
import glob
import re
import difflib
import random

# ═════════════════════════════════════════════════════════════════════════════
# ENVIRONMENT VARIABLES & CONFIGURATION
# ═════════════════════════════════════════════════════════════════════════════
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY", "")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")
THESPORTSDB_KEY = os.environ.get("THESPORTSDB_KEY", "")
# OpenRouter (free-tier LLM aggregator). When unset, publisher falls back to Gemini, then to local template.
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
GENERATED_IMG_DIR = os.path.join(PROJECT_DIR, "images", "generated")
os.makedirs(GENERATED_IMG_DIR, exist_ok=True)

# ═════════════════════════════════════════════════════════════════════════════
# TASK 7: TELEGRAM NOTIFICATION VIA SENDPHOTO
# ═════════════════════════════════════════════════════════════════════════════
def send_telegram_notification(title, article_url, image_path):
    if not TELEGRAM_TOKEN or not CHAT_ID:
        print("Telegram notification skipped: TELEGRAM_TOKEN or CHAT_ID not set.")
        return
        
    caption = f"*New football article published on GoalPulse!*\n\n*{title}*\n\n[Read the full article here]({article_url})"
    
    if image_path.startswith("http"):
        public_img_url = image_path
    else:
        clean_path = image_path.lstrip("./").lstrip("/")
        public_img_url = f"https://gooalpulse.netlify.app/{clean_path}"

    photo_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendPhoto"
    payload = {
        "chat_id": CHAT_ID,
        "photo": public_img_url,
        "caption": caption,
        "parse_mode": "Markdown"
    }
    
    try:
        resp = requests.post(photo_url, json=payload, timeout=12)
        if resp.status_code == 200:
            print("Telegram photo notification sent successfully.")
            return
    except Exception as e:
        print("Telegram sendPhoto failed, falling back to sendMessage:", e)

    msg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    msg_payload = {
        "chat_id": CHAT_ID,
        "text": caption,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(msg_url, json=msg_payload, timeout=10)
    except Exception as e:
        print("Telegram sendMessage fallback failed:", e)


# ═════════════════════════════════════════════════════════════════════════════
# TASK 6 & ISSUE 1: PEXELS API LEGAL IMAGE FETCHING (DIVERSE ENTITY MAPPING)
# ═════════════════════════════════════════════════════════════════════════════
LOCAL_FALLBACK_POOL = [
    ("images/hero.webp", ""),
    ("images/press-conference.webp", ""),
    ("images/celebration-contrast.webp", ""),
    ("images/walking-away.webp", ""),
    ("images/world-cup-trophy.webp", ""),
    ("images/press-conference-mobile.webp", ""),
    ("images/celebration-contrast-mobile.webp", ""),
]

def get_smart_local_fallback(title, slug=None):
    """Smartly matches title keywords to the most relevant local image asset.
    When slug is provided, ensures a deterministic but diverse pick so adjacent
    articles do not share the same image."""
    t_lower = title.lower()
    rapid_match = None
    if any(k in t_lower for k in ['barcelona', 'barca', 'برشلونة', 'press', 'مؤتمر']):
        rapid_match = ("images/press-conference.webp", "")
    elif any(k in t_lower for k in ['real madrid', 'madrid', 'مدريد', 'الريال', 'stadium']):
        rapid_match = ("images/hero.webp", "")
    elif any(k in t_lower for k in ['trophy', 'cup', 'final', 'champions', 'كأس', 'نهائي', 'البطولة']):
        rapid_match = ("images/world-cup-trophy.webp", "")
    elif any(k in t_lower for k in ['injury', 'shock', 'leave', 'out', 'إصابة', 'صدمة', 'خروج', 'استبعاد']):
        rapid_match = ("images/walking-away.webp", "")
    elif any(k in t_lower for k in ['win', 'goal', 'celebrate', 'bellingham', 'ronaldo', 'messi', 'فوز', 'احتفال']):
        rapid_match = ("images/celebration-contrast.webp", "")

    if slug:
        used = set()
        for f in glob.glob(os.path.join(GENERATED_IMG_DIR, "*.jpg")):
            used.add(os.path.basename(f))
        hash_val = sum(ord(c) for c in (title + slug))
        pool = list(LOCAL_FALLBACK_POOL)
        for i in range(len(pool)):
            candidate = pool[(hash_val + i * 7) % len(pool)]
            if candidate[0] not in used or len(used) >= len(pool):
                return candidate
        return pool[hash_val % len(pool)]
    if rapid_match:
        return rapid_match
    hash_val = sum(ord(c) for c in title)
    return LOCAL_FALLBACK_POOL[hash_val % len(LOCAL_FALLBACK_POOL)]

def fetch_wikimedia_image(title, slug):
    """No-key fallback using Wikimedia Commons API — returns diverse, copyright-free images."""
    if not slug:
        return get_smart_local_fallback(title, slug)
    cache_path = os.path.join(GENERATED_IMG_DIR, f"post_{slug}.jpg")
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 4000:
        return (f"images/generated/post_{slug}.jpg",
                '<figcaption style="font-size:12px; color:#64748b; margin-top:6px; text-align:center;">Photo via Wikimedia Commons (CC)</figcaption>')

    entity_queries = {
        "ريال مدريد": "Real Madrid", "Real Madrid": "Real Madrid",
        "برشلونة": "FC Barcelona", "Barcelona": "FC Barcelona",
        "ليفربول": "Liverpool F.C.", "Liverpool": "Liverpool F.C.",
        "مانشستر سيتي": "Manchester City F.C.", "Man City": "Manchester City F.C.",
        "أرسنال": "Arsenal F.C.", "Arsenal": "Arsenal F.C.",
        "بايرن": "FC Bayern Munich", "Bayern": "FC Bayern Munich",
        "باريس": "Paris Saint-Germain", "PSG": "Paris Saint-Germain",
        "الهلال": "Al-Hilal SFC", "النصر": "Al-Nassr FC",
        "ميسي": "Lionel Messi", "Messi": "Lionel Messi",
        "رونالدو": "Cristiano Ronaldo", "Ronaldo": "Cristiano Ronaldo",
        "مبابي": "Kylian Mbappé", "Mbappe": "Kylian Mbappé",
        "بيلينغهام": "Jude Bellingham", "Bellingham": "Jude Bellingham",
        "الدوري السعودي": "Saudi Pro League",
        "دوري أبطال أوروبا": "UEFA Champions League", "Champions League": "UEFA Champions League",
    }
    search_query = "association football stadium"
    for term, q in entity_queries.items():
        if term.lower() in title.lower():
            search_query = q
            break

    try:
        api_url = (
            "https://commons.wikimedia.org/w/api.php?action=query&format=json&prop=imageinfo"
            "&iiprop=url|extmetadata&iiurlwidth=900&generator=search&gsrnamespace=6"
            f"&gsrsearch={urllib.parse.quote(search_query)}&gsrlimit=12"
        )
        resp = requests.get(api_url, timeout=10, headers={"User-Agent": "GoalPulse/1.0 (editorial)"})
        if resp.status_code == 200:
            pages = resp.json().get("query", {}).get("pages", {})
            candidates = list(pages.values())
            random.shuffle(candidates)
            for p in candidates:
                ii = p.get("imageinfo", [{}])[0]
                img_url = ii.get("thumburl") or ii.get("url")
                if not img_url:
                    continue
                if not img_url.lower().split("?", 1)[0].endswith((".jpg", ".jpeg", ".png")):
                    continue
                img_resp = requests.get(img_url, timeout=20,
                                        headers={"User-Agent": "GoalPulse/1.0 (editorial)"})
                if img_resp.status_code == 200 and len(img_resp.content) > 6000:
                    with open(cache_path, "wb") as f:
                        f.write(img_resp.content)
                    print(f"WIKIMEDIA_IMG cached ({len(img_resp.content)} bytes) -> {img_url[:60]}")
                    return (f"images/generated/post_{slug}.jpg",
                            '<figcaption style="font-size:12px; color:#64748b; margin-top:6px; text-align:center;">Photo via Wikimedia Commons (CC)</figcaption>')
        else:
            print(f"WIKIMEDIA_API error status={resp.status_code}")
    except Exception as e:
        print("Wikimedia fetch failed:", e)
    print("WIKIMEDIA_FALLBACK_LOCAL")
    return get_smart_local_fallback(title, slug)


def fetch_pexels_image(title, slug):
    if not PEXELS_API_KEY:
        print("WARNING: PEXELS_API_KEY is not set — using Wikimedia Commons fallback image")
        print("IMAGE_SOURCE=wikimedia_fallback")
        return fetch_wikimedia_image(title, slug)

    cache_path = os.path.join(GENERATED_IMG_DIR, f"post_{slug}.jpg")
    attribution_html = '<figcaption style="font-size:12px; color:#64748b; margin-top:6px; text-align:center;">Photo via Pexels</figcaption>'
    if os.path.exists(cache_path) and os.path.getsize(cache_path) > 4000:
        print("IMAGE_SOURCE=pexels_cached")
        return f"images/generated/post_{slug}.jpg", attribution_html

    entity_queries = {
        "ريال مدريد": "Real Madrid football team stadium",
        "Real Madrid": "Real Madrid football team stadium",
        "برشلونة": "FC Barcelona soccer match",
        "Barcelona": "FC Barcelona soccer match",
        "ليفربول": "Liverpool football club action",
        "Liverpool": "Liverpool football club action",
        "مانشستر سيتي": "Manchester City football players",
        "Man City": "Manchester City football players",
        "Manchester City": "Manchester City football players",
        "مانشستر يونايتد": "Manchester United Old Trafford",
        "Manchester United": "Manchester United Old Trafford",
        "أرسنال": "Arsenal FC football match",
        "Arsenal": "Arsenal FC football match",
        "بايرن": "Bayern Munich football",
        "Bayern": "Bayern Munich football",
        "باريس": "Paris Saint Germain football",
        "PSG": "Paris Saint Germain football",
        "الهلال": "Al Hilal football club Saudi",
        "النصر": "Al Nassr Saudi football",
        "ميسي": "Lionel Messi Argentina football action",
        "Messi": "Lionel Messi Argentina football action",
        "رونالدو": "Cristiano Ronaldo celebration soccer",
        "Ronaldo": "Cristiano Ronaldo celebration soccer",
        "مبابي": "Kylian Mbappe football player",
        "Mbappe": "Kylian Mbappe football player",
        "بيلينغهام": "Jude Bellingham England football",
        "Bellingham": "Jude Bellingham England football",
        "الدوري السعودي": "Saudi Pro League football stadium",
        "Saudi": "Saudi Pro League football stadium",
        "دوري أبطال أوروبا": "UEFA Champions League trophy match",
        "Champions League": "UEFA Champions League trophy match"
    }

    t_lower = title.lower()
    search_query = "football soccer match action stadium"
    for term, query in entity_queries.items():
        if term.lower() in t_lower:
            search_query = query
            break

    diverse_queries = [
        "stadium floodlights football match",
        "football players celebrating goal",
        "soccer championship trophy celebration",
        "professional football match action",
        "football fans cheering in stadium"
    ]
    if search_query == "football soccer match action stadium":
        hash_val = sum(ord(c) for c in title)
        search_query = diverse_queries[hash_val % len(diverse_queries)]

    url = f"https://api.pexels.com/v1/search?query={urllib.parse.quote(search_query)}&per_page=15"
    headers = {"Authorization": PEXELS_API_KEY}

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            photos = data.get("photos", [])
            if photos:
                photo = random.choice(photos)
                img_download_url = photo.get("src", {}).get("large") or photo.get("src", {}).get("medium")
                photographer = photo.get("photographer", "Pexels Contributor")
                photographer_url = photo.get("photographer_url", "https://www.pexels.com")
                
                if img_download_url:
                    img_resp = requests.get(img_download_url, timeout=15)
                    if img_resp.status_code == 200:
                        save_filename = f"post_{slug}.jpg"
                        save_path = os.path.join(GENERATED_IMG_DIR, save_filename)
                        with open(save_path, "wb") as f:
                            f.write(img_resp.content)
                            
                        relative_img_path = f"images/generated/{save_filename}"
                        attribution_html = f'<figcaption style="font-size:12px; color:#64748b; margin-top:6px; text-align:center;">Photo: <a href="{photographer_url}" target="_blank" rel="noopener" style="color:#3b82f6; text-decoration:none;">{photographer}</a> via Pexels</figcaption>'
                        print("IMAGE_SOURCE=pexels")
                        return relative_img_path, attribution_html
    except Exception as e:
        print("Pexels fetch failed:", e)

    print("IMAGE_SOURCE=wikimedia_fallback_after_pexels_fail")
    return fetch_wikimedia_image(title, slug)



# ═════════════════════════════════════════════════════════════════════════════
def clean_headline(raw_title: str) -> str:
    """
    Robustly strips publisher names or domain suffixes from Google News RSS titles.
    Handles 0, 1, or multiple trailing ' - Source' segments, validating domains/publishers.
    """
    if not raw_title:
        return ""
    title = raw_title.strip()
    while True:
        match = re.search(r'^(.*?)\s*-\s+([^-]+)$', title)
        if not match:
            break
        base, suffix = match.groups()
        suffix_clean = suffix.strip()
        is_domain = bool(re.search(r'\.[a-z]{2,}$', suffix_clean, re.IGNORECASE))
        is_common_source = suffix_clean.lower() in [
            'bbc.com', 'skysports.com', 'espn.com', 'guardian.com', 'goal.com',
            'thesun.co.uk', 'dailymail.co.uk', 'mailonline.com', 'mirror.co.uk',
            'express.co.uk', 'independent.co.uk', 'telegraph.co.uk', 'marca.com',
            'as.com', 'sport.es', 'mundodeportivo.com', 'gazzetta.it', 'tuttosport.com',
            'kicker.de', 'bild.de', 'lequipe.fr', 'rmc.fr', 'football.london',
            '90min.com', 'standard.co.uk', 'football365.com', 'planetasport.com'
        ]
        if is_domain or is_common_source or len(suffix_clean.split()) <= 3:
            title = base.strip()
        else:
            break
    return title


# ─────────────────────────────────────────────────────────────────────────────
# Title sanitization (P0-2): reject garbage/clickbait RSS headlines before they
# ever get published verbatim into HTML, JSON-LD, meta tags, or Telegram.
# ─────────────────────────────────────────────────────────────────────────────

# Emoji & "variation selector / ZWJ" ranges that clickbait headlines abuse.
_EMOJI_RE = re.compile(
    "["
    "\U0001F300-\U0001FAFF"   # pictographs, symbols, transport
    "\U00002600-\U000027BF"   # misc symbols & dingbats
    "\U0001F1E0-\U0001F1FF"   # regional indicators
    "\U0000FE0F\U0000200D"    # variation selector + ZWJ
    "\U00002B50\U00002705\U0000274C\U00002757"
    "]"
)

# Bare parenthesised opaque IDs like "(Rm7Tb8AY4O)" glue-joined from broken feeds.
_SUSPICIOUS_ID_RE = re.compile(r"\([A-Za-z0-9]{6,}\)")

# Football relevance signals (English + Arabic + common entities).
_FOOTBALL_KEYWORDS = [
    # English
    "football", "soccer", "premier league", "champions league", "la liga", "serie a",
    "bundesliga", "ligue 1", "europa league", "world cup", "uefa", "fifa",
    "transfer", "signing", "goal", "match", "derby", "fixture", "striker",
    "midfielder", "defender", "goalkeeper", "manager", "coach", "club", "fc",
    # Arabic
    "كرة", "رياضة", "مباراة", "هدف", "دوري", "كأس", "منتخب", "نادي", "لاعب",
    "مدرب", "انتقال", "تشكيلة", "إصابة", "فوز", "خسارة", "تعادل", "نهائي",
    "ريال", "برشلونة", "البارسا", "ليفربول", "أرسنال", "مانشستر", "سيتي",
    "باريس", "يوفنتوس", "ميلان", "إنتر", "بايرن", "دورتموند", "تشيلسي",
    "السعودية", "الأهلي", "النصر", "الاتحاد", "الهلال", "إسبانيا", "كأس العالم",
    # Entities
    "madrid", "barcelona", "barca", "arsenal", "liverpool", "chelsea", "united",
    "city", "tottenham", "bayern", "dortmund", "psg", "juventus", "milan", "inter",
    "ronaldo", "messi", "mbapp", "mbappe", "haaland", "bellingham", "salah",
]


def strip_emoji(text: str) -> str:
    """Remove decorative/clickbait emoji and collapse the whitespace they leave."""
    cleaned = _EMOJI_RE.sub(" ", text or "")
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def is_plausible_headline(title: str) -> bool:
    """True only when the cleaned title looks like a real football headline.

    Rejects glue-joined spam (opaque parenthesised IDs), excessive emoji density,
    and titles that carry zero football relevance signal.
    """
    if not title:
        return False
    if _SUSPICIOUS_ID_RE.search(title):
        return False
    # Emoji density guard: an otherwise short title with several emoji is clickbait.
    emoji_count = len(_EMOJI_RE.findall(title))
    if emoji_count >= 3 or (emoji_count >= 1 and len(title) < 40):
        return False
    lowered = title.lower()
    return any(kw in lowered for kw in _FOOTBALL_KEYWORDS)


def sanitize_trending_title(raw_title: str) -> str:
    """Full pipeline: strip publisher suffix -> strip emoji -> collapse whitespace."""
    return strip_emoji(clean_headline(raw_title))


# ═════════════════════════════════════════════════════════════════════════════
# TASK 1: REAL TRENDING-TOPIC DETECTION
# ═════════════════════════════════════════════════════════════════════════════
def fetch_top_trending_news():
    search_queries = [
        "Premier League breaking transfer news",
        "Real Madrid Champions League update",
        "FC Barcelona La Liga match today",
        "Manchester City Liverpool Premier League",
        "UEFA Champions League fixtures results",
        "Serie A Juventus AC Milan Inter",
        "Bundesliga Bayern Munich Dortmund",
        "European football transfer gossip"
    ]

    all_entries = []
    entity_counts = {}
    high_interest_keywords = ['breaking', 'signing', 'deal', 'official', 'injury', 'goal', 'win', 'champions', 'transfer', 'match']

    for q in search_queries:
        try:
            encoded_query = urllib.parse.quote(q)
            rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en&gl=GB&ceid=GB:en"
            feed = feedparser.parse(rss_url)
            for entry in feed.entries[:4]:
                title = entry.title
                title_clean = sanitize_trending_title(title)

                # P0-2: skip glue-joined spam / non-football / emoji-heavy garbage.
                if not is_plausible_headline(title_clean):
                    continue

                score = 0
                for kw in high_interest_keywords:
                    if kw.lower() in title_clean.lower():
                        score += 2

                entities = ['madrid', 'barcelona', 'arsenal', 'liverpool', 'manchester', 'city', 'united', 'bayern', 'psg', 'juventus', 'milan', 'champions', 'premier']
                for ent in entities:
                    if ent.lower() in title_clean.lower():
                        score += 3
                        entity_counts[ent] = entity_counts.get(ent, 0) + 1

                source = entry.get('source', {}).get('title', 'GoalPulse European Desk')
                all_entries.append({
                    'title': title_clean,
                    'source': source,
                    'score': score
                })
        except Exception as e:
            print("Error parsing RSS feed:", e)

    if not all_entries:
        title = "European Football Giants Prepare for Crucial Weekend Showdowns"
        source = "GoalPulse Editorial Desk"
        return title, source

    for item in all_entries:
        for ent, count in entity_counts.items():
            if ent in item['title']:
                item['score'] += (count * 2)

    all_entries.sort(key=lambda x: x['score'], reverse=True)
    # P0-2: instead of blindly taking #1, return the first *plausible* candidate.
    # (Every surviving entry already passed is_plausible_headline above, so this
    # loop is belt-and-braces: if scoring ever changes it still can't regress.)
    for candidate in all_entries:
        if is_plausible_headline(candidate["title"]):
            return candidate["title"], candidate["source"]

    # All scored candidates failed plausibility (paranoia path) — use editorial fallback.
    title = "European Football Giants Prepare for Crucial Weekend Showdowns"
    source = "GoalPulse Editorial Desk"
    return title, source


# ═════════════════════════════════════════════════════════════════════════════
# TASK 2 & ISSUE 2: GEMINI API ARTICLE GENERATOR + ROBUST ADSTERRA BANNERS
# ═════════════════════════════════════════════════════════════════════════════

TRENDING_ENTITIES = {
    'real madrid': {'name': 'Real Madrid', 'context': 'the record 15-time European champions', 'discover_tags': ['Real Madrid', 'Los Blancos', 'Bernabeu']},
    'barcelona': {'name': 'FC Barcelona', 'context': 'the Catalan giants chasing domestic and continental glory', 'discover_tags': ['Barcelona', 'Barca', 'Camp Nou']},
    'liverpool': {'name': 'Liverpool', 'context': 'the Anfield outfit under Arne Slot', 'discover_tags': ['Liverpool', 'Anfield', 'Mohamed Salah']},
    'manchester city': {'name': 'Manchester City', 'context': 'Pep Guardiola\u2019s treble-chasing squad', 'discover_tags': ['Man City', 'Pep Guardiola', 'Erling Haaland']},
    'man city': {'name': 'Manchester City', 'context': 'Pep Guardiola\u2019s treble-chasing squad', 'discover_tags': ['Man City', 'Pep Guardiola', 'Erling Haaland']},
    'arsenal': {'name': 'Arsenal', 'context': 'Mikel Arteta\u2019s Premier League title contenders', 'discover_tags': ['Arsenal', 'Emirates', 'Bukayo Saka']},
    'chelsea': {'name': 'Chelsea', 'context': 'the Stamford Bridge rebuild under Enzo Maresca', 'discover_tags': ['Chelsea', 'Stamford Bridge']},
    'bayern': {'name': 'Bayern Munich', 'context': 'the Bundesliga powerhouse', 'discover_tags': ['Bayern Munich', 'Harry Kane', 'Allianz Arena']},
    'psg': {'name': 'Paris Saint-Germain', 'context': 'the Ligue 1 champions navigating the post-Mbappe era', 'discover_tags': ['PSG', 'Paris Saint-Germain', 'Parc des Princes']},
    'juventus': {'name': 'Juventus', 'context': 'the Turin giants fighting for Serie A supremacy', 'discover_tags': ['Juventus', 'Bianconeri']},
    'inter': {'name': 'Inter Milan', 'context': 'the Nerazzurri chasing back-to-back Serie A titles', 'discover_tags': ['Inter Milan', 'Nerazzurri', 'San Siro']},
    'milan': {'name': 'AC Milan', 'context': 'the Rossoneri battling in Serie A and Europe', 'discover_tags': ['AC Milan', 'Rossoneri', 'San Siro']},
    'atletico': {'name': 'Atletico Madrid', 'context': 'Diego Simeone\u2019s relentless squad', 'discover_tags': ['Atletico Madrid', 'Simeone']},
    'dortmund': {'name': 'Borussia Dortmund', 'context': 'the Yellow Wall and their Champions League ambitions', 'discover_tags': ['Dortmund', 'BVB', 'Signal Iduna Park']},
    'tottenham': {'name': 'Tottenham Hotspur', 'context': 'Spurs chasing a return to the Champions League', 'discover_tags': ['Tottenham', 'Spurs', 'Son Heung-min']},
    'newcastle': {'name': 'Newcastle United', 'context': 'the Saudi-backed project rising in the Premier League', 'discover_tags': ['Newcastle', 'St James Park']},
    'mohamed salah': {'name': 'Mohamed Salah', 'context': 'Liverpool\u2019s Egyptian King and Premier League top-scorer contender', 'discover_tags': ['Mohamed Salah', 'Mo Salah', 'Liverpool']},
    'salah': {'name': 'Mohamed Salah', 'context': 'Liverpool\u2019s Egyptian King and Premier League top-scorer contender', 'discover_tags': ['Mohamed Salah', 'Mo Salah', 'Liverpool']},
    'mbappe': {'name': 'Kylian Mbappe', 'context': 'the French superstar now leading the line at Real Madrid', 'discover_tags': ['Kylian Mbappe', 'Real Madrid', 'France']},
    'haaland': {'name': 'Erling Haaland', 'context': 'Manchester City\u2019s goal machine breaking Premier League records', 'discover_tags': ['Erling Haaland', 'Man City', 'Premier League']},
    'vinicius': {'name': 'Vinicius Junior', 'context': 'Real Madrid\u2019s Brazilian winger and Ballon d\u2019Or contender', 'discover_tags': ['Vinicius Jr', 'Real Madrid', 'Brazil']},
    'bellingham': {'name': 'Jude Bellingham', 'context': 'Real Madrid\u2019s English midfield talisman', 'discover_tags': ['Jude Bellingham', 'Real Madrid', 'England']},
    'saka': {'name': 'Bukayo Saka', 'context': 'Arsenal\u2019s dynamic winger and England international', 'discover_tags': ['Bukayo Saka', 'Arsenal', 'England']},
    'kane': {'name': 'Harry Kane', 'context': 'Bayern Munich\u2019s prolific striker chasing Bundesliga golden boot', 'discover_tags': ['Harry Kane', 'Bayern Munich', 'England']},
    'rodrigo': {'name': 'Rodri', 'context': 'Manchester City\u2019s midfield anchor and Ballon d\u2019Or winner', 'discover_tags': ['Rodri', 'Man City', 'Spain']},
    'yamal': {'name': 'Lamine Yamal', 'context': 'Barcelona\u2019s teenage phenom and Spain\u2019s Euro 2024 star', 'discover_tags': ['Lamine Yamal', 'Barcelona', 'Spain']},
    'champions league': {'name': 'UEFA Champions League', 'context': 'Europe\u2019s elite club competition', 'discover_tags': ['Champions League', 'UCL', 'European football']},
    'ucl': {'name': 'UEFA Champions League', 'context': 'Europe\u2019s elite club competition', 'discover_tags': ['Champions League', 'UCL']},
    'premier league': {'name': 'Premier League', 'context': 'the most-watched domestic league in world football', 'discover_tags': ['Premier League', 'English football']},
    'la liga': {'name': 'La Liga', 'context': 'Spain\u2019s top flight featuring El Clasico rivalries', 'discover_tags': ['La Liga', 'Spanish football', 'El Clasico']},
    'serie a': {'name': 'Serie A', 'context': 'Italy\u2019s historic top division', 'discover_tags': ['Serie A', 'Italian football']},
    'bundesliga': {'name': 'Bundesliga', 'context': 'Germany\u2019s high-octane top flight', 'discover_tags': ['Bundesliga', 'German football']},
    'ligue 1': {'name': 'Ligue 1', 'context': 'France\u2019s top division', 'discover_tags': ['Ligue 1', 'French football']},
    'europa league': {'name': 'UEFA Europa League', 'context': 'Europe\u2019s second-tier club competition', 'discover_tags': ['Europa League', 'UEFA']},
    'transfer': {'name': 'Transfer Market', 'context': 'the summer transfer window shaping squads across Europe', 'discover_tags': ['transfer', 'signing', 'football transfer']},
    'signing': {'name': 'Transfer Market', 'context': 'the summer transfer window shaping squads across Europe', 'discover_tags': ['transfer', 'signing']},
}


def detect_trending_entities(title):
    """Detect big-name teams, players, and competitions mentioned in the headline."""
    t_lower = title.lower()
    detected = []
    for key, info in TRENDING_ENTITIES.items():
        if key in t_lower:
            detected.append(info)
    seen_names = set()
    unique = []
    for d in detected:
        if d['name'] not in seen_names:
            unique.append(d)
            seen_names.add(d['name'])
    return unique


def build_discover_context(title):
    """Build contextual string linking the headline to trending entities for Discover algorithms."""
    entities = detect_trending_entities(title)
    if not entities:
        return ""

    names = [e['name'] for e in entities]
    context_sentences = []
    for e in entities[:4]:
        context_sentences.append(f"{e['name']} ({e['context']})")

    all_tags = []
    for e in entities[:4]:
        all_tags.extend(e['discover_tags'])

    context_block = "ENTITY CONTEXT for Google Discover optimization: "
    context_block += ". ".join(context_sentences) + ". "
    context_block += f"Trending entities to naturally mention: {', '.join(all_tags[:8])}. "
    context_block += "Weave these names and themes naturally into the narrative where contextually relevant. "
    context_block += "Do not force unrelated mentions \u2014 only link entities that have a plausible connection to the headline story."
    return context_block


def fetch_web_search_snippets(query, max_results=5):
    """Free web search via DuckDuckGo's HTML endpoint (no API key, no dependency).

    Returns a list of dicts: {"title", "snippet", "url"} for the top results.
    Returns an empty list on any failure — callers must treat empty gracefully
    (the prompt continues without LIVE SEARCH CONTEXT).
    """
    if not query:
        return []
    try:
        # Endpoint serves plain HTML — parse with regex (robust enough for snippets).
        url = "https://html.duckduckgo.com/html/"
        params = {"q": f"{query} football news 2026", "kl": "us-en"}
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        }
        resp = requests.post(url, data=params, headers=headers, timeout=12)
        if resp.status_code not in (200, 202):
            print(f"DuckDuckGo search returned status={resp.status_code} — skipping live context")
            return []
        html = resp.text

        # Each result is wrapped in <a class="result__a" href="...">title</a>
        # followed by <a class="result__snippet" href="...">snippet</a>
        results = []
        # Use finditer with two patterns and merge by order
        titles = list(re.finditer(
            r'<a[^>]+class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.DOTALL
        ))
        snippets = list(re.finditer(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html, re.DOTALL
        ))
        for i, t in enumerate(titles[:max_results]):
            entry = {
                "title": re.sub(r"<[^>]+>", "", t.group(2)).strip(),
                "url": t.group(1),
                "snippet": "",
            }
            if i < len(snippets):
                entry["snippet"] = re.sub(r"<[^>]+>", "", snippets[i].group(1)).strip()
            if entry["title"]:
                results.append(entry)
        print(f"DUCKDUCKGO_SEARCH count={len(results)} query={query!r}")
        return results
    except Exception as e:
        print(f"DuckDuckGo web search failed: {e} — continuing without live context")
        return []


def generate_deep_1200_words_article(title, matches_data=None):
    ad_banner_1 = """
        <div class="ad-container-728" style="margin:20px auto; text-align:center; min-height:90px;" loading="lazy">
            <script type="text/javascript">
                atOptions = {
                    'key' : '82bdfd8fd781c6112b908116a83c04d9',
                    'format' : 'iframe',
                    'height' : 90,
                    'width' : 728,
                    'params' : {}
                };
            </script>
            <script type="text/javascript" src="https://www.highperformanceformat.com/82bdfd8fd781c6112b908116a83c04d9/invoke.js"></script>
        </div>
    """

    ad_banner_2 = """
        <div class="ad-container-728 ad-after-content" style="margin:20px auto; text-align:center; min-height:90px;" loading="lazy" aria-label="sponsor">
            <div class="ad-sep" data-i18n="ad_label">Featured Ad - Adsterra</div>
            <script async="async" data-cfasync="false" src="https://pl30650962.effectivecpmnetwork.com/29fb4cec1b995ab1738cf1b8e766a785/invoke.js"></script>
            <div id="container-29fb4cec1b995ab1738cf1b8e766a785"></div>
        </div>
    """

    # Build the editorial prompt once so OpenRouter (primary) and Gemini (secondary)
    # share the same instructions, ad-banner injection rules, and content cleansing.
    match_context = ""
    if matches_data:
        match_context = "Today's live match data: " + json.dumps(matches_data[:2], ensure_ascii=False)

    discover_context = build_discover_context(title)

    # ── FREE WEB SEARCH CONTEXT (DuckDuckGo, no API key) ──────────────────
    # Pull 3-5 snippets for real-time details (transfer fees, match events, club
    # statements). On any failure, fetch_web_search_snippets returns [] and we
    # continue without live context — the LLM still works from the headline alone.
    search_results = fetch_web_search_snippets(title, max_results=5)
    live_search_context = ""
    if search_results:
        context_lines = []
        for i, r in enumerate(search_results, 1):
            ctx = f"[{i}] {r['title']}"
            if r["snippet"]:
                ctx += f" — {r['snippet']}"
            context_lines.append(ctx)
        live_search_context = (
            "\nLIVE SEARCH CONTEXT (real-time snippets from DuckDuckGo — use these "
            "facts to ground the article, but do NOT copy verbatim):\n"
            + "\n".join(context_lines) + "\n"
        )
        print(f"LIVE_SEARCH_CONTEXT count={len(search_results)} chars={len(live_search_context)}")
    else:
        print("LIVE_SEARCH_CONTEXT=empty (DuckDuckGo unavailable or 0 results)")

    prompt_text = f"""
You are a world-class chief sports editor at GoalPulse, a leading European football authority.
Write an authoritative, high-converting, and SEO-optimized news article in English about the following headline:
"{title}"
{match_context}

{live_search_context}

{discover_context}

Key Directives for Top Google Discover & Search Performance:
1. Start with an intense, high-impact lead paragraph inside <p class="lead">...</p> naming the key entities, high stakes, and official stance.
2. Structure the content into clear, punchy, engaging paragraphs.
3. HIGH-INTENT & PSYCHOLOGICAL TRIGGERS: Naturally incorporate high-converting intent phrases where relevant (e.g., "official announcement", "exclusive tactical analysis", "transfer saga update", "confirmed lineup status", "manager breakdown").
4. ENTITY LINKING FOR GOOGLE DISCOVER: Weave in trending entities ({', '.join([e['name'] for e in detect_trending_entities(title)])}) and their broader European/Champions League context seamlessly.
5. ANTI-SPAM COMPLIANCE: Do NOT use repetitive filler phrases or keyword stuffing. Ensure every paragraph provides genuine editorial value, strategic context, or tactical insight anchored strictly to facts.
6. Use clear, descriptive subheadings <h2>...</h2> matching natural search queries (never generic labels).
7. Include a dedicated FAQ section <h2>Frequently Asked Questions</h2> with 2-3 precise Q&As formatted inside <div style="background:#f8fafc; border:1px solid #e2e8f0; padding:18px; border-radius:8px; margin-bottom:20px;">.
8. No emojis in headings or body. Return ONLY valid HTML for the article body.
9. Target minimum length: 1200 words across at least 5 <h2> sections to ensure depth and SEO performance.
"""

    def _inject_ad_banners(generated_text):
        """Strip markdown fences and insert Adsterra ads between <h2> sections.

        Shared by OpenRouter (primary) and Gemini (secondary). Returns the final
        HTML on success, or None if the generated text is too short to publish.
        """
        if not generated_text or len(generated_text) < 300:
            return None
        # Strip ```html ... ``` markdown wrappers (some LLMs wrap the answer)
        text = re.sub(r'^```(?:html)?\s*', '', generated_text, flags=re.MULTILINE)
        text = re.sub(r'```\s*$', '', text, flags=re.MULTILINE).strip()
        paragraphs = text.split("<h2>")
        if len(paragraphs) >= 4:
            return paragraphs[0] + "<h2>" + paragraphs[1] + ad_banner_1 + "<h2>" + "<h2>".join(paragraphs[2:-1]) + ad_banner_2 + "<h2>" + paragraphs[-1]
        if len(paragraphs) == 3:
            return paragraphs[0] + "<h2>" + paragraphs[1] + ad_banner_1 + "<h2>" + paragraphs[2] + ad_banner_2
        return text + ad_banner_1

    # ────────────────────────────────────────────────────────────────────────
    # Primary AI article generator — OpenRouter (free-tier chat completions)
    # ────────────────────────────────────────────────────────────────────────
    if OPENROUTER_API_KEY:
        try:
            openrouter_url = "https://openrouter.ai/api/v1/chat/completions"
            openrouter_headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                # OpenRouter tracking compliance — identifies the site.
                "HTTP-Referer": "https://gooalpulse.netlify.app/",
                "X-Title": "GoalPulse",
            }
            openrouter_payload = {
                "model": "openrouter/free",  # free tier — exact provider resolved OpenRouter-side
                "messages": [
                    {"role": "system", "content": "You are an expert sports journalist. "
                                                  "Output ONLY valid HTML for the article body. "
                                                  "Use the LIVE SEARCH CONTEXT to ground every claim in facts."},
                    {"role": "user", "content": prompt_text},
                ],
                "temperature": 0.7,
                "max_tokens": 2000,
            }
            resp = requests.post(openrouter_url, headers=openrouter_headers, json=openrouter_payload, timeout=30)
            if resp.status_code == 200:
                data = resp.json()
                choices = data.get("choices") or []
                if choices:
                    generated_text = choices[0].get("message", {}).get("content", "")
                    final_html = _inject_ad_banners(generated_text)
                    if final_html:
                        print("CONTENT_SOURCE=openrouter")
                        return final_html
                else:
                    print("OpenRouter returned 200 but no choices in payload")
            else:
                print(f"OpenRouter API returned status={resp.status_code} (rate-limit or quota) — falling back")
        except Exception as e:
            print("OpenRouter API call failed, falling back to Gemini / local generator:", e)

    # ────────────────────────────────────────────────────────────────────────
    # Secondary AI article generator — Gemini (genai flash-latest)
    # ────────────────────────────────────────────────────────────────────────
    if GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"

            payload = {
                "contents": [{
                    "parts": [{"text": prompt_text}]
                }]
            }

            resp = requests.post(url, json=payload, timeout=25)
            if resp.status_code == 200:
                result = resp.json()
                generated_text = result.get("candidates", [])[0].get("content", {}).get("parts", [])[0].get("text", "")
                final_html = _inject_ad_banners(generated_text)
                if final_html:
                    print("CONTENT_SOURCE=gemini")
                    return final_html
        except Exception as e:
            print("Gemini API call failed, falling back to dynamic generator:", e)


    print("CONTENT_SOURCE=fallback_template")
    entities = detect_trending_entities(title)
    keywords = re.sub(r'[^\w\s]', '', title).split()
    entity_hints = [w for w in keywords if len(w) > 3]
    topic_focus = " ".join(entity_hints[:5]) if entity_hints else title

    # Build entity-aware lead paragraph
    if entities:
        primary = entities[0]
        entity_names = ", ".join([e['name'] for e in entities[:3]])
        lead_text = (f'The story surrounding "{topic_focus}" is reverberating across European football, '
                      f'with <strong>{primary["name"]}</strong> \u2014 {primary["context"]} \u2014 '
                      f'at the center of the conversation. For fans tracking {entity_names}, '
                      f'this development carries significant implications.')
    else:
        lead_text = (f'Developments surrounding "{topic_focus}" are dominating European football discussions '
                      f'and media headlines as clubs brace for decisive fixtures.')

    # Build contextual entity paragraphs
    entity_para_1 = ""
    entity_para_2 = ""
    if not entities:
        entity_para_1 = ('This development lands at a pivotal moment in the European football calendar. '
                         'With the Premier League, La Liga, Serie A, and Bundesliga all in full swing, '
                         'and the UEFA Champions League knockout stages on the horizon, any shift '
                         'in the competitive landscape can have cascading effects for clubs like '
                         'Real Madrid, Manchester City, Liverpool, and Bayern Munich.')
        entity_para_2 = ('Star players such as Mohamed Salah, Kylian Mbappe, Erling Haaland, and Jude Bellingham '
                         'continue to dominate search trends and Google Discover feeds. '
                         'Wherever this story touches their respective clubs or competitions, '
                         'the implications are amplified for millions of engaged readers.')
    elif len(entities) >= 2:
        e1, e2 = entities[0], entities[1]
        entity_para_1 = (f'The ripple effects extend beyond {e1["name"]} alone. '
                         f'{e2["name"]}, {e2["context"]}, find themselves drawn into the narrative '
                         f'either as direct rivals, interested observers, or parties whose trajectory '
                         f'could be altered by the outcome.')
    else:
        e1 = entities[0]
        # Pick a complementary entity from discover tags
        comp_entities = []
        for tag in e1.get('discover_tags', []):
            for k, info in TRENDING_ENTITIES.items():
                if info['name'] != e1['name'] and tag.lower() in info['name'].lower() and info['name'] not in [c['name'] for c in comp_entities]:
                    comp_entities.append(info)
                    break
        if comp_entities:
            e2 = comp_entities[0]
            entity_para_1 = (f'The ripple effects extend beyond {e1["name"]} alone. '
                             f'{e2["name"]}, {e2["context"]}, could see their own campaigns reshaped '
                             f'depending on how this situation unfolds.')
        else:
            entity_para_1 = f'The broader European football landscape, including the Champions League and rival domestic contenders, will be watching closely.'

    if not entities:
        pass  # entity_para_2 already set above
    elif len(entities) >= 3:
        e3 = entities[2]
        entity_para_2 = (f'Meanwhile, {e3["name"]} \u2014 {e3["context"]} \u2014 add another layer of intrigue. '
                         f'Their relevance to this story underlines how interconnected the European football '
                         f'ecosystem has become, where a single development can shift the balance across multiple competitions.')
    elif len(entities) == 2:
        # Add Champions League or Premier League as a discover magnet
        if not any('Champions League' in e['name'] or 'Premier League' in e['name'] for e in entities):
            entity_para_2 = ('The wider UEFA Champions League picture adds further weight to this story. '
                             'With Europe\u2019s elite clubs all vying for continental supremacy, '
                             'any shift in momentum can cascade across tournaments and influence the Knockout draw seeding.')
        else:
            entity_para_2 = 'The broader competitive landscape across European football ensures this story will remain a focal point for fans and analysts alike.'
    else:
        # Single entity — fill para_2 with broader European context
        if not any('Champions League' in e['name'] or 'Premier League' in e['name'] for e in entities):
            entity_para_2 = ('The wider UEFA Champions League picture adds further weight to this story. '
                             'With Europe\u2019s elite clubs all vying for continental supremacy, '
                             'any shift in momentum can cascade across tournaments and influence the knockout draw seeding.')
        else:
            entity_para_2 = 'The broader competitive landscape across European football ensures this story will remain a focal point for fans and analysts alike.'

    # Discover-optimized FAQ
    faq_q1 = f"What does {topic_focus} mean for the European football season?"
    faq_a1 = "It could shift standings, influence transfer strategy, and reshape the Champions League qualification picture for the clubs involved."
    if entities:
        faq_q1 = f"How does this affect {entities[0]['name']} and their rivals?"
        faq_a1 = f"{entities[0]['name']}, {entities[0]['context']}, face direct consequences. " + (
            f"Rivals such as {entities[1]['name']} will be watching for any opening." if len(entities) >= 2 else "The competitive balance could shift significantly."
        )

    faq_q2 = "Which players and teams should fans watch closely?"
    if entities:
        star_names = ", ".join([e['name'] for e in entities[:3]])
        faq_a2 = f"Key figures include {star_names}. Each carries Champions League or domestic title implications that Google Discover users are actively searching for."
    else:
        faq_a2 = "Watch the top European clubs and their star players, as developments here ripple across the Premier League, La Liga, Serie A, and Champions League."

    fallback_html = f"""
        <p class="lead">{lead_text}</p>

        <h2>Strategic Context & Wider Implications</h2>
        <p>{entity_para_1}</p>
        <p>{entity_para_2}</p>

        {ad_banner_1}

        <h2>Tactical Outlook & What Comes Next</h2>
        <p>For {topic_focus}, the coming weeks are decisive. Managerial decisions, tactical adjustments, and injury management will all factor into how the situation resolves itself across domestic and European fronts.</p>

        <h2>Frequently Asked Questions</h2>
        <div style="background:#f8fafc; border:1px solid #e2e8f0; padding:18px; border-radius:8px; margin-bottom:20px;">
            <p style="font-weight:bold; color:var(--primary); margin-bottom:5px;">Q: {faq_q1}</p>
            <p style="font-size:14.5px; margin-bottom:15px; color:#475569;">A: {faq_a1}</p>
            <p style="font-weight:bold; color:var(--primary); margin-bottom:5px;">Q: {faq_q2}</p>
            <p style="font-size:14.5px; margin-bottom:15px; color:#475569;">A: {faq_a2}</p>
            <p style="font-weight:bold; color:var(--primary); margin-bottom:5px;">Q: How is GoalPulse covering this story?</p>
            <p style="font-size:14.5px; color:#475569;">A: Through real-time match center coverage, live editorial updates, and continuous tracking of European football developments on GoalPulse.</p>
        </div>

        {ad_banner_2}

        <h2>Conclusion & Upcoming Fixtures</h2>
        <p>GoalPulse will continue to monitor all updates surrounding {topic_focus} and deliver official announcements as they happen. Stay tuned for matchday coverage, tactical breakdowns, and transfer developments across the Premier League, La Liga, Serie A, Bundesliga, and the UEFA Champions League.</p>
    """
    return fallback_html


# ═════════════════════════════════════════════════════════════════════════════
# TASK 3 & 9: DUPLICATE PREVENTION & CLEANUP
# ═════════════════════════════════════════════════════════════════════════════
def normalize_title_for_comparison(title):
    stopwords = {'in', 'on', 'at', 'the', 'a', 'an', 'of', 'for', 'to', 'with', 'and', 'or',
                 'يلا', 'عاجل', 'رسميا', 'رسمياً', 'مباراة', 'اليوم', 'بث',
                 'في', 'من', 'على', 'أن', 'عن', 'إلى', 'التي', 'الذي', 'و', 'الـ'}
    words = re.sub(r'[^\w\s]', '', title).split()
    filtered = [w.lower() for w in words if w not in stopwords and len(w) > 1]
    return set(filtered)

def is_too_similar_to_recent_posts(new_title, threshold=0.58):
    pattern = os.path.join(PROJECT_DIR, "post_*.html")
    files = glob.glob(pattern)
    now = datetime.now()
    
    new_norm = normalize_title_for_comparison(new_title)
    entities = ['مدريد', 'برشلونة', 'الهلال', 'النصر', 'ميسي', 'رونالدو', 'الأهلي', 'الزمالك', 'ليفربول', 'مانشستر', 'الجزائر', 'مولودية', 'شبيبة', 'دوري', 'كأس', 'سيتي', 'أرسنال', 'بايرن', 'باريس']
    new_entities = {ent for ent in entities if ent in new_title}
    
    for f in files:
        filename = os.path.basename(f)
        m_date = re.search(r'post_(\d{14})\.html', filename)
        if m_date:
            try:
                post_dt = datetime.strptime(m_date.group(1), "%Y%m%d%H%M%S")
                if (now - post_dt) > timedelta(hours=48):
                    continue
            except Exception:
                pass
                
        try:
            with open(f, "r", encoding="utf-8") as file:
                content = file.read()
                m_title = re.search(r'<title>(.*?)\|', content)
                if m_title:
                    existing_title = m_title.group(1).strip()
                    existing_norm = normalize_title_for_comparison(existing_title)
                    
                    similarity = difflib.SequenceMatcher(None, new_title, existing_title).ratio()
                    if similarity >= threshold:
                        return True
                        
                    if new_norm and existing_norm:
                        intersection = new_norm.intersection(existing_norm)
                        union = new_norm.union(existing_norm)
                        jaccard = len(intersection) / len(union) if union else 0
                        if jaccard >= 0.50:
                            return True
                            
                    existing_entities = {ent for ent in entities if ent in existing_title}
                    common_entities = new_entities.intersection(existing_entities)
                    if len(common_entities) >= 2:
                        return True
        except Exception:
            pass
    return False


def get_recent_published_titles(limit=10):
    """Return the most recent published post titles (newest first)."""
    pattern = os.path.join(PROJECT_DIR, "post_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    titles = []
    for f in files[:limit]:
        try:
            with open(f, "r", encoding="utf-8") as file:
                content = file.read()
                m_title = re.search(r'<title>(.*?)\|', content)
                if m_title:
                    titles.append(m_title.group(1).strip())
        except Exception:
            pass
    return titles


def is_duplicate_via_ai(new_title, recent_titles=None):
    """AI-powered semantic duplicate detection.

    Uses OpenRouter (primary) then Gemini (fallback) to decide whether the new
    headline is a semantic repeat of any recently published headline — catches
    cases the classic difflib/Jaccard dedup misses (rewording, synonyms, or a
    different framing of the same story).

    Returns True if DUPLICATE, False if NOVEL, None if the AI could not decide
    (callers must treat None as "not a duplicate" so publishing never blocks).
    """
    if not new_title:
        return None
    if recent_titles is None:
        recent_titles = get_recent_published_titles(limit=10)
    if not recent_titles:
        return False

    import json as _json
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(recent_titles))
    ai_prompt = (
        "You are a football news editor. Decide whether the NEW headline below "
        "is a semantic duplicate of ANY headline in the RECENTLY PUBLISHED list.\n\n"
        f"NEW HEADLINE:\n{new_title}\n\n"
        f"RECENTLY PUBLISHED:\n{numbered}\n\n"
        "Treat two headlines as DUPLICATES if they describe the SAME football "
        "story (same match, transfer, quote, press statement, injury, or event) "
        "even when worded differently. Treat them as NOVEL if they cover a "
        "distinct fixture, club, player, competition, or angle.\n\n"
        'Reply with ONLY one of these JSON objects:\n'
        '  {"decision":"DUPLICATE","index":N,"reason":"..."}\n'
        '  {"decision":"NOVEL","reason":"..."}\n'
        "Do not add any other text."
    )

    def _parse_ai_decision(text):
        if not text:
            return None
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            data = _json.loads(text)
        except Exception:
            m = re.search(r'"decision"\s*:\s*"(DUPLICATE|NOVEL)"', text)
            if m:
                return True if m.group(1) == "DUPLICATE" else False
            return None
        decision = (data.get("decision") or "").upper()
        if decision == "DUPLICATE":
            idx = (data.get("index") or 1) - 1
            matched = recent_titles[idx][:60] if 0 <= idx < len(recent_titles) else "?"
            print(f"  AI_DEDUP duplicate matched recent_title={matched!r}")
            return True
        if decision == "NOVEL":
            return False
        return None

    if OPENROUTER_API_KEY:
        try:
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://gooalpulse.netlify.app/",
                "X-Title": "GoalPulse-Dedup",
            }
            payload = {
                "model": "openrouter/free",
                "messages": [
                    {"role": "system", "content": "You classify football news duplicates. Output only JSON."},
                    {"role": "user", "content": ai_prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 200,
            }
            r = requests.post(url, headers=headers, json=payload, timeout=20)
            if r.status_code == 200:
                choices = r.json().get("choices") or []
                content = choices[0].get("message", {}).get("content", "") if choices else ""
                decision = _parse_ai_decision(content)
                if decision is not None:
                    print("AI_DEDUP_SOURCE=openrouter")
                    return decision
        except Exception as e:
            print(f"AI_DEDUP OpenRouter error (non-fatal): {e}")

    if GEMINI_API_KEY:
        try:
            url = ("https://generativelanguage.googleapis.com/v1beta/models/"
                    f"gemini-flash-latest:generateContent?key={GEMINI_API_KEY}")
            payload = {"contents": [{"parts": [{"text": ai_prompt}]}]}
            r = requests.post(url, json=payload, timeout=20)
            if r.status_code == 200:
                parts = r.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
                content = parts[0].get("text", "") if parts else ""
                decision = _parse_ai_decision(content)
                if decision is not None:
                    print("AI_DEDUP_SOURCE=gemini")
                    return decision
        except Exception as e:
            print(f"AI_DEDUP Gemini error (non-fatal): {e}")

    print("AI_DEDUP_SOURCE=none (no key/unanswered — classic dedup still runs)")
    return None


def determine_article_category(title):
    t_lower = title.lower()
    if any(k in t_lower for k in ['premier league', 'arsenal', 'chelsea', 'liverpool', 'manchester united', 'man city', 'tottenham']):
        return 'premier-league', 'Premier League'
    elif any(k in t_lower for k in ['champions league', 'ucl', 'real madrid', 'barcelona', 'bayern', 'psg', 'juventus', 'milan', 'inter']):
        return 'ucl', 'Champions League'
    elif any(k in t_lower for k in ['transfer', 'signing', 'deal', 'bid', 'contract', 'loan']):
        return 'transfers', 'Transfer Market'
    elif any(k in t_lower for k in ['la liga', 'serie a', 'bundesliga', 'ligue 1', 'atletico']):
        return 'leagues', 'European Leagues'
    else:
        return 'general', 'Football News'


def generate_search_index():
    posts = get_existing_posts()
    search_data = []
    for p in posts:
        if p['file'] != "index.html":
            cat_class, cat_name = determine_article_category(p['title'])
            search_data.append({
                "title": p['title'],
                "url": p['file'],
                "image": p['image'],
                "category": cat_name
            })
    with open(os.path.join(PROJECT_DIR, "search-index.json"), "w", encoding="utf-8") as f:
        json.dump(search_data, f, ensure_ascii=False, indent=2)


def generate_archive_page():
    posts = [p for p in get_existing_posts() if p['file'] != "index.html"]
    
    archive_items_html = ""
    for p in posts:
        cat_class, cat_name = determine_article_category(p['title'])
        archive_items_html += f"""
        <div class="news-card archive-card" data-category="{cat_name}">
            <img src="{p['image']}" alt="{p['title']}" class="news-card-img" loading="lazy" width="130" height="90" onerror="this.onerror=null;this.src='images/hero.webp';">
            <div class="news-card-body">
                <span class="category-tag {cat_class}">{cat_name}</span>
                <a href="{p['file']}" class="news-card-title">{p['title']}</a>
            </div>
        </div>
        """
        
    archive_html = f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Article Archive | GoalPulse</title>
    <meta name="description" content="Archive of European football coverage, exclusive stories, and articles via GoalPulse.">
    <link rel="stylesheet" href="css/portal.css">
    <link rel="icon" type="image/webp" href="images/logo.webp">
</head>
<body>
    <nav class="navbar">
        <a href="index.html" class="brand-logo">
            <img src="images/logo.webp" alt="GoalPulse Logo" style="height:38px; width:auto; border-radius:6px; object-fit:contain;"> <span>GoalPulse</span>
        </a>
        <div class="navbar-actions">
            <a href="index.html" class="theme-toggle-btn">Home</a>
        </div>
    </nav>
    <main class="main-layout" style="display:block; max-width:900px; margin:40px auto; padding:0 15px;">
        <h1 style="font-size:26px; font-weight:900; margin-bottom:20px; border-left:4px solid var(--accent-red); padding-left:12px;">Full Article Archive</h1>
        <div class="news-grid" id="archiveGrid">
            {archive_items_html}
        </div>
    </main>
    <footer>
        <p>&copy; 2026 GoalPulse. All Rights Reserved.</p>
    </footer>
</body>
</html>
"""
    with open(os.path.join(PROJECT_DIR, "archive.html"), "w", encoding="utf-8") as f:
        f.write(archive_html)


def _extract_title_from_html(content: str, fallback: str = "") -> str:
    """Extract the canonical article title from a rendered post page.

    Priority order (most-robust first):
      1. Explicit `<!-- ARTICLE_TITLE: ... -->` marker (immune to '|' in titles).
      2. The JSON-LD NewsArticle 'headline' (structured, unambiguous).
      3. Legacy regex on <title> ... | Brand — keeps backward compatibility.
    """
    m = re.search(r"<!--\s*ARTICLE_TITLE:\s*(.*?)\s*-->", content, re.DOTALL)
    if m:
        return m.group(1).strip()
    m = re.search(r'<script type="application/ld\+json">(.*?)</script>', content, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(1))
            graph = data.get("@graph", [data]) if isinstance(data, dict) else data
            for node in (graph if isinstance(graph, list) else [graph]):
                if isinstance(node, dict) and node.get("@type") == "NewsArticle" and node.get("headline"):
                    return str(node["headline"]).strip()
        except Exception:
            pass
    m = re.search(r"<title>(.*?)\s*\|\s*GoalPulse\s*</title>", content)
    if m:
        return m.group(1).strip()
    return fallback


def get_existing_posts():
    posts = []
    pattern = os.path.join(PROJECT_DIR, "post_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    
    seen_titles = []
    for f in files:
        filename = os.path.basename(f)
        try:
            with open(f, "r", encoding="utf-8") as file:
                content = file.read()
                title = _extract_title_from_html(content, fallback=filename)
                
                is_duplicate = False
                new_norm = normalize_title_for_comparison(title)
                for existing_title in seen_titles:
                    similarity = difflib.SequenceMatcher(None, title, existing_title).ratio()
                    existing_norm = normalize_title_for_comparison(existing_title)
                    jaccard = 0
                    if new_norm and existing_norm:
                        intersection = new_norm.intersection(existing_norm)
                        union = new_norm.union(existing_norm)
                        jaccard = len(intersection) / len(union) if union else 0
                    
                    if similarity >= 0.50 or jaccard >= 0.50 or title == existing_title:
                        is_duplicate = True
                        break
                
                if is_duplicate:
                    continue
                    
                seen_titles.append(title)
                
                m_img = re.search(r'class="hero-img"[^>]*?\ssrc="(.*?)"', content)
                if not m_img:
                    m_img = re.search(r'src="(.*?)"[^>]*?class="hero-img"', content)
                img = m_img.group(1) if m_img else "images/hero.webp"
                # Publication date for sitemaps/RSS: prefer the embedded ISO datetime,
                # fall back to the filename timestamp.
                m_iso = re.search(r'<time[^>]*datetime="([^"]+)"', content)
                if m_iso:
                    pub_iso = m_iso.group(1)
                else:
                    m_ts = re.search(r'post_(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', filename)
                    pub_iso = (f"{m_ts.group(1)}-{m_ts.group(2)}-{m_ts.group(3)}T"
                               f"{m_ts.group(4)}:{m_ts.group(5)}:{m_ts.group(6)}+00:00") if m_ts else datetime.now().isoformat()
                cat_class, cat_name = determine_article_category(title)
                posts.append({"file": filename, "title": title, "image": img,
                              "cat_class": cat_class, "cat_name": cat_name, "pub_iso": pub_iso})
        except:
            pass
            
    if os.path.exists(os.path.join(PROJECT_DIR, "index.html")):
        posts.append({
            "file": "index.html",
            "title": "تغطيات وحصريات مباريات اليوم ونتائج البطولات المباشرة",
            "image": "images/hero.webp",
            "cat_class": "general",
            "cat_name": "أخبار عامة"
        })
    return posts


def html_escape(text):
    """Escape text for safe use in HTML attribute values and element content."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
                      .replace('"', "&quot;").replace("'", "&#39;")


def js_string_escape(text):
    """Escape a Python str so it can be safely placed INSIDE an existing JS "..." string.

    JSON.dumps already handles quotes, backslashes, newlines, unicode; we strip the
    outer quotes it adds (the template supplies them) and additionally neutralise
    the two U+2028/U+2029 line-separator chars that can break JS parsing.
    """
    if not text:
        return ""
    dumped = json.dumps(str(text), ensure_ascii=False)[1:-1]
    return dumped.replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def get_absolute_image_url(image_url):
    """Convert a site-relative image path to an absolute URL for OG/JSON-LD/RSS."""
    if image_url and image_url.startswith("http"):
        return image_url
    return f"https://gooalpulse.netlify.app/{(image_url or '').lstrip('/')}"


def build_related_articles_html(all_posts, current_filename, count=3):
    """Build the Related Articles cards linking the most recent other posts."""
    cards = ""
    related = [p for p in all_posts if p["file"] != current_filename and p["file"] != "index.html"][:count]
    for p in related:
        safe_t = html_escape(p["title"])
        img = p["image"] or "images/hero.webp"
        cards += f"""
                    <a href="{p['file']}" class="related-card">
                        <img src="{img}" alt="{safe_t} - GoalPulse" loading="lazy" onerror="this.onerror=null;this.src='images/hero.webp';">
                        <span class="related-title">{safe_t}</span>
                    </a>"""
    return cards


def _responsive_variant_candidates(relative_src: str):
    """For a local image path, return the avif/mobile/srcset sources when the
    corresponding files actually exist on disk. Returns None for remote URLs
    (Pexels etc.) so the caller can simply fall back to a plain <img>."""
    if not relative_src or relative_src.startswith("http"):
        return None
    base = relative_src.lstrip("/")
    root, ext = os.path.splitext(base)
    avif = f"{root}.avif"
    mobile_webp = f"{root}-mobile.webp"
    mobile_avif = f"{root}-mobile.avif"
    full_avif = os.path.join(PROJECT_DIR, avif.replace("/", os.sep))
    full_mwebp = os.path.join(PROJECT_DIR, mobile_webp.replace("/", os.sep))
    full_mavif = os.path.join(PROJECT_DIR, mobile_avif.replace("/", os.sep))
    if not (os.path.exists(full_avif) or os.path.exists(full_mwebp) or os.path.exists(full_mavif)):
        return None
    return {
        "avif": f"/{avif}" if os.path.exists(full_avif) else None,
        "mobile_webp": f"/{mobile_webp}" if os.path.exists(full_mwebp) else None,
        "mobile_avif": f"/{mobile_avif}" if os.path.exists(full_mavif) else None,
        "fallback": f"/{base}",
    }


def make_picture_tag(
    src: str,
    alt: str,
    css_class: str = "",
    loading: str = "lazy",
    sizes: str = "(max-width: 600px) 420px, 850px",
    style: str = "",
    attrs: str = "",
    width: int = None,
    height: int = None,
    fetchpriority: str = "",
) -> str:
    """Return a <picture> element when responsive siblings exist, else <img>.

    Handles Pexels-jpg (single file), local webp with .avif/-mobile siblings,
    and already-existing static images equally without template surgery.
    """
    cl = f' class="{html_escape(css_class)}"' if css_class else ""
    dim = f' width="{width}" height="{height}"' if width and height else ""
    st = f' style="{html_escape(style)}"' if style else ""
    at = f" {attrs}" if attrs else ""
    fp = f' fetchpriority="{fetchpriority}"' if fetchpriority else ""
    fallback_attr = ' onerror="this.onerror=null;this.src=\'images/hero.webp\';"'
    safe_src = html_escape(src)
    safe_alt = html_escape(alt)

    variants = _responsive_variant_candidates(src)
    if not variants:
        return (
            f'<img src="{safe_src}" alt="{safe_alt}"{cl}{dim}{st} loading="{loading}"{fp}{at}{fallback_attr}>'
        )
    sources = []
    if variants["mobile_avif"]:
        sources.append(
            f'<source media="(max-width: 600px)" type="image/avif" srcset="{variants["mobile_avif"]}">'
        )
    if variants["avif"]:
        sources.append(f'<source type="image/avif" srcset="{variants["avif"]}">')
    if variants["mobile_webp"]:
        sources.append(
            f'<source media="(max-width: 600px)" type="image/webp" srcset="{variants["mobile_webp"]}">'
        )
    if variants["fallback"].lower().endswith(".webp"):
        sources.append(
            f'<source type="image/webp" srcset="{variants["fallback"]}" sizes="{sizes}">'
        )
    sources_html = "".join(sources)
    return (
        f'<picture>{sources_html}'
        f'<img src="{safe_src}" alt="{safe_alt}"{cl}{dim}{st} loading="{loading}"{fp}{at}{fallback_attr}>'
        f"</picture>"
    )


ARTICLE_RETENTION_DAYS = 14  # Articles older than 2 weeks are deleted to keep the site fresh.


# Static images that have generated -mobile / .avif variants on disk
# (verified via `images/` listing: hero, world-cup-trophy, walking-away,
# press-conference, celebration-contrast). srcset enables the browser to pick
# the lightest, crispest option per viewport without JS.
_RESPONSIVE_STATIC_IMAGES = {
    "images/hero.webp": {
        "avif": "images/hero.avif",
        "webp_srcset": "images/hero.webp 850w, images/hero-mobile.webp 420w",
        "mobile": "images/hero-mobile.webp",
    },
    "images/world-cup-trophy.webp": {
        "avif": "images/world-cup-trophy.avif",
        "webp_srcset": "images/world-cup-trophy.webp 850w, images/world-cup-trophy-mobile.webp 420w",
        "mobile": "images/world-cup-trophy-mobile.webp",
    },
    "images/walking-away.webp": {
        "avif": "images/walking-away.avif",
        "webp_srcset": "images/walking-away.webp 850w, images/walking-away-mobile.webp 420w",
        "mobile": "images/walking-away-mobile.webp",
    },
    "images/press-conference.webp": {
        "avif": "images/press-conference.avif",
        "webp_srcset": "images/press-conference.webp 850w, images/press-conference-mobile.webp 420w",
        "mobile": "images/press-conference-mobile.webp",
    },
    "images/celebration-contrast.webp": {
        "avif": "images/celebration-contrast.avif",
        "webp_srcset": "images/celebration-contrast.webp 850w, images/celebration-contrast-mobile.webp 420w",
        "mobile": "images/celebration-contrast-mobile.webp",
    },
}


def make_picture_tag(
    src: str,
    alt: str,
    css_class: str = "",
    loading: str = "lazy",
    sizes: str = "(max-width: 600px) 420px, 850px",
    style: str = "",
    attrs: str = "",
    width: int = None,
    height: int = None,
) -> str:
    """Return a <picture> element wrapping `src` with AVIF + mobile + webp fallbacks.

    For images *without* generated variants (e.g. Pexels-fetched post_NNNNN.jpg)
    the caller should keep using a plain <img>; this helper only upgrades images
    that have known responsive variants in `_RESPONSIVE_STATIC_IMAGES`.
    """
    if src not in _RESPONSIVE_STATIC_IMAGES:
        dim = f' width="{width}" height="{height}"' if width and height else ""
        st = f' style="{style}"' if style else ""
        at = f" {attrs}" if attrs else ""
        cl = f' class="{css_class}"' if css_class else ""
        return (f'<img src="{html_escape(src)}" alt="{html_escape(alt)}"'
                f'{cl}{dim}{st} loading="{loading}"{at}>')

    v = _RESPONSIVE_STATIC_IMAGES[src]
    cl = f' class="{css_class}"' if css_class else ""
    dim = f' width="{width}" height="{height}"' if width and height else ""
    st = f' style="{style}"' if style else ""
    at = f" {attrs}" if attrs else ""
    return (
        f'<picture>'
        f'<source type="image/avif" srcset="{v["avif"]}">'
        f'<source media="(max-width: 600px)" type="image/webp" srcset="{v["mobile"]}">'
        f'<source type="image/webp" srcset="{v["webp_srcset"]}" sizes="{sizes}">'
        f'<img src="{html_escape(src)}" alt="{html_escape(alt)}"'
        f'{cl}{dim}{st} loading="{loading}"{at}>'
        f"</picture>"
    )


ARTICLE_RETENTION_DAYS = 14  # Articles older than 2 weeks are deleted to keep the site fresh.

def cleanup_old_articles():
    """Delete post_*.html files older than ARTICLE_RETENTION_DAYS (14 days).

    Runs at the start of every publishing run. Older articles are removed so the
    homepage archive, sitemaps and Google Discover feed stay accurate and the
    Netlify deploy footprint stays small. Logs how many were removed.
    """
    pattern = os.path.join(PROJECT_DIR, "post_*.html")
    files = glob.glob(pattern)
    now = datetime.now()
    removed = 0

    for f in files:
        filename = os.path.basename(f)
        m = re.search(r'post_(\d{14})\.html', filename)
        is_old = False

        if m:
            try:
                post_dt = datetime.strptime(m.group(1), "%Y%m%d%H%M%S")
                if (now - post_dt) > timedelta(days=ARTICLE_RETENTION_DAYS):
                    is_old = True
            except Exception:
                pass
        else:
            mtime = datetime.fromtimestamp(os.path.getmtime(f))
            if (now - mtime) > timedelta(days=ARTICLE_RETENTION_DAYS):
                is_old = True

        if is_old:
            try:
                os.remove(f)
                removed += 1
            except Exception:
                pass

    if removed:
        print(f"CLEANUP: removed {removed} article(s) older than {ARTICLE_RETENTION_DAYS} days")
    return removed


NEUTRAL_LOGO_SVG = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' width='24' height='24'><circle cx='12' cy='12' r='10' fill='%23cbd5e1'/><path d='M12 2a10 10 0 0 1 10 10 10 10 0 0 1-10 10A10 10 0 0 1 2 12 10 10 0 0 1 12 2zm0 2a8 8 0 0 0-8 8 8 8 0 0 0 8 8 8 8 0 0 0 8-8 8 8 0 0 0-8-8z' fill='%2364748b'/></svg>"

# WARNING: NEVER return hardcoded/fictional fixtures here. Empty list is the only acceptable fallback.
def get_live_matches_data():
    api_key = os.environ.get("FOOTBALL_API_KEY")
    if not api_key:
        print("FOOTBALL_API_KEY is not set — live match data will be unavailable")
        print("MATCH_DATA_SOURCE=empty_no_api_key")
        return []

    today_dt = datetime.utcnow()
    tomorrow_dt = today_dt + timedelta(days=1)
    
    today_str = today_dt.strftime("%Y-%m-%d")
    tomorrow_str = tomorrow_dt.strftime("%Y-%m-%d")

    headers = {"x-apisports-key": api_key}
    fixtures = []

    for d_str in [today_str, tomorrow_str]:
        url = f"https://v3.football.api-sports.io/fixtures?date={d_str}"
        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                fixtures.extend(data.get("response", []))
        except Exception as e:
            print(f"Error fetching fixtures for {d_str}:", e)

    if not fixtures:
        print("MATCH_DATA_SOURCE=empty_no_fixtures")
        return []

    matches = []
    priority_league_ids = [2, 39, 140, 135, 78, 307, 186]

    priority_fixtures = [f for f in fixtures if f.get('league', {}).get('id') in priority_league_ids]
    other_fixtures = [f for f in fixtures if f.get('league', {}).get('id') not in priority_league_ids]
    selected_fixtures = (priority_fixtures + other_fixtures)[:8]

    for fix in selected_fixtures:
        fixture_info = fix.get('fixture', {})
        league_info = fix.get('league', {})
        teams_info = fix.get('teams', {})
        goals_info = fix.get('goals', {})
        status_info = fixture_info.get('status', {})

        status_short = status_info.get('short', 'NS')
        elapsed = status_info.get('elapsed')

        kickoff_raw = fixture_info.get('date', '')
        try:
            dt = datetime.fromisoformat(kickoff_raw.replace('Z', '+00:00'))
            time_str = dt.strftime("%H:%M UTC")
        except Exception:
            time_str = "اليوم"

        home_team = teams_info.get('home', {}).get('name', 'Home')
        away_team = teams_info.get('away', {}).get('name', 'Home')
        home_logo = teams_info.get('home', {}).get('logo') or NEUTRAL_LOGO_SVG
        away_logo = teams_info.get('away', {}).get('logo') or NEUTRAL_LOGO_SVG
        league_name = league_info.get('name', 'مباراة حية')

        home_goals = goals_info.get('home')
        away_goals = goals_info.get('away')

        if status_short in ['1H', '2H', 'HT', 'ET', 'P', 'LIVE']:
            score = f"{home_goals if home_goals is not None else 0} - {away_goals if away_goals is not None else 0}"
            time_display = f"مباشر ({elapsed}')" if elapsed else "مباشر"
            status_class = "status-live"
            possession = "إحصائيات المباشرة جارية"
            shots = "تغطية حية"
        elif status_short in ['FT', 'AET', 'PEN']:
            score = f"{home_goals if home_goals is not None else 0} - {away_goals if away_goals is not None else 0}"
            time_display = "انتهت"
            status_class = "status-ft"
            possession = "انتهت المباراة"
            shots = "نتيجة نهائية"
        else:
            score = "VS"
            time_display = time_str
            status_class = "status-upcoming"
            possession = "لم تبدأ المباراة بعد"
            shots = "قريباً"

        matches.append({
            "league": league_name,
            "time": time_display,
            "status_class": status_class,
            "home": home_team,
            "away": away_team,
            "home_logo": home_logo,
            "away_logo": away_logo,
            "home_goals": home_goals if home_goals is not None else 0,
            "away_goals": away_goals if away_goals is not None else 0,
            "score": score,
            "possession": possession,
            "shots": shots,
            "lineup_home": "تعلن التشكيلة الرسمية قبل الانطلاق.",
            "lineup_away": "تعلن التشكيلة الرسمية قبل الانطلاق."
        })

    print(f"MATCH_DATA_SOURCE=api_football count={len(matches)}")
    return matches


def get_top_match_ticker_html(matches=None):
    if matches is None:
        matches = get_live_matches_data()
    if not matches:
        return '<div class="match-ticker-card"><span class="ticker-text">Live coverage of the top European and world football matches today</span></div>'
        
    ticker_items = ""
    for m in matches:
        badge_class = m.get('status_class', 'status-upcoming')
        is_live = 'status-live' in badge_class
        live_dot = '<span class="live-dot">●</span> ' if is_live else ''
        
        ticker_items += f"""
        <div class="match-ticker-card" onclick="openMatchModal('{m['league']}')">
            <div class="ticker-card-header">
                <span class="ticker-league-title">{m['league']}</span>
                <span class="ticker-status-pill {badge_class}">{live_dot}{m['time']}</span>
            </div>
            <div class="ticker-teams-wrap">
                <div class="ticker-team-row">
                    <img src="{m['home_logo']}" class="team-crest" alt="{m['home']}" onerror="this.style.display='none';">
                    <span class="team-name">{m['home']}</span>
                </div>
                <div class="ticker-score-badge">{m['score']}</div>
                <div class="ticker-team-row">
                    <span class="team-name">{m['away']}</span>
                    <img src="{m['away_logo']}" class="team-crest" alt="{m['away']}" onerror="this.style.display='none';">
                </div>
            </div>
        </div>
        """
    return ticker_items


def get_modal_matches_html(matches=None):
    if matches is None:
        matches = get_live_matches_data()
    if not matches:
        return '<div class="match-card empty-state"><p>No live matches available at the moment. Stay tuned for the next update.</p></div>'
        
    modal_html = ""
    for idx, m in enumerate(matches):
        badge_class = m.get('status_class', 'status-upcoming')
        is_live = 'status-live' in badge_class
        live_indicator = '<span class="live-pulse"></span>' if is_live else ''
        
        # Determine winning team highlighting if finished (safe None handling)
        hg = m.get('home_goals') if m.get('home_goals') is not None else 0
        ag = m.get('away_goals') if m.get('away_goals') is not None else 0
        home_win = "winner" if hg > ag and 'status-ft' in badge_class else ""
        away_win = "winner" if ag > hg and 'status-ft' in badge_class else ""

        modal_html += f"""
        <div class="match-card" data-status="{badge_class}" data-league="{m['league']}">
            <div class="match-card-header">
                <div class="match-league-info">
                    <span class="league-icon"><span style="color:#dc2626;">★</span></span>
                    <span class="league-name">{m['league']}</span>
                </div>
                <div class="match-status-badge {badge_class}">
                    {live_indicator} <span>{m['time']}</span>
                </div>
            </div>
            
            <div class="match-card-body">
                <div class="match-team-col home {home_win}">
                    <img src="{m['home_logo']}" class="team-crest-large" alt="{m['home']}" onerror="this.style.display='none';">
                    <span class="team-title">{m['home']}</span>
                </div>
                
                <div class="match-score-block">
                    <span class="score-display">{m['score']}</span>
                    <span class="score-subtext">Half / Time</span>
                </div>
                
                <div class="match-team-col away {away_win}">
                    <img src="{m['away_logo']}" class="team-crest-large" alt="{m['away']}" onerror="this.style.display='none';">
                    <span class="team-title">{m['away']}</span>
                </div>
            </div>
            
            <button class="match-stats-toggle-btn" onclick="toggleMatchDetails('details-{idx}')">
                <span>Match details, stats and lineups</span>
                <span class="chevron-icon"><span style="color:#dc2626;">▼</span></span>
            </button>
            
            <div id="details-{idx}" class="match-details-box" style="display:none;">
                <div class="stats-section">
                    <h4 class="section-subtitle">Match statistics & facts</h4>
                    
                    {f'''
                    <div class="stat-progress-item">
                        <div class="stat-labels">
                            <span>{m['home']}</span>
                            <span class="stat-title">Possession / Status</span>
                            <span>{m['away']}</span>
                        </div>
                        <div class="stat-bar-track">
                            <div class="stat-bar-fill home-fill" style="width: 50%;"></div>
                            <div class="stat-bar-fill away-fill" style="width: 50%;"></div>
                        </div>
                        <div class="stat-desc-text">{m['possession']}</div>
                    </div>
                    
                    <div class="stat-progress-item">
                        <div class="stat-labels">
                            <span>{m['home']}</span>
                            <span class="stat-title">Shots & attempts</span>
                            <span>{m['away']}</span>
                        </div>
                        <div class="stat-bar-track">
                            <div class="stat-bar-fill home-fill" style="width: 50%;"></div>
                            <div class="stat-bar-fill away-fill" style="width: 50%;"></div>
                        </div>
                        <div class="stat-desc-text">{m['shots']}</div>
                    </div>
                    ''' if badge_class != 'status-upcoming' else f'''
                    <div class="stat-progress-item">
                        <div class="stat-labels">
                            <span>{m['home']}</span>
                            <span class="stat-title">Match status</span>
                            <span>{m['away']}</span>
                        </div>
                        <div class="stat-desc-text" style="padding: 10px; background: #f1f5f9; border-radius: 6px; color: #475569; font-weight: 700;">{m['possession']}</div>
                    </div>
                    '''}
                </div>

                <div class="lineups-section">
                    <h4 class="section-subtitle">Expected & announced lineups</h4>
                    <div class="lineup-grid">
                        <div class="lineup-box home-lineup">
                            <strong class="team-lineup-header">{m['home']}</strong>
                            <p>{m['lineup_home']}</p>
                        </div>
                        <div class="lineup-box away-lineup">
                            <strong class="team-lineup-header">{m['away']}</strong>
                            <p>{m['lineup_away']}</p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        """
    return modal_html


def generate_seo_keywords(title):
    """
    Generates maximum-performing, Google-safe SEO keywords combining:
    1. Pre-existing base keywords (never removed)
    2. Psychological & High-Intent triggers (exclusive, breaking, tactical analysis, official statement)
    3. Dynamic entity-specific search terms (teams, players, leagues)
    4. Anti-spam deduplication & natural distribution for Google Search & Discover compliance.
    """
    words = re.sub(r'[^\w\s]', '', title).split()
    
    # 1. Base Core Keywords (Preserved 100%)
    base_keywords = [
        "football news",
        "European football",
        "Premier League",
        "Champions League",
        "GoalPulse",
        "football today",
        "match results",
        "transfer news"
    ]
    
    # 2. Psychological & High-Intent Search Triggers
    psychological_triggers = [
        "breaking transfer news",
        "official announcement",
        "exclusive update",
        "tactical breakdown",
        "confirmed lineup",
        "injury status",
        "contract extension saga",
        "manager reaction"
    ]
    
    # 3. Dynamic Entity-Specific Search Terms
    entities = detect_trending_entities(title)
    entity_keywords = []
    for e in entities[:4]:
        name = e['name']
        entity_keywords.append(name)
        entity_keywords.append(f"{name} transfer news")
        entity_keywords.append(f"{name} match analysis")
        for tag in e.get('discover_tags', [])[:2]:
            entity_keywords.append(tag)
            
    # 4. Headline-derived N-gram terms
    extracted = [w for w in words if len(w) > 3 and w.lower() not in ['news', 'today', 'breaking', 'update', 'watch', 'live']][:6]
    
    combined = base_keywords + psychological_triggers + entity_keywords + extracted
    
    # Anti-Spam deduplication preserving priority order
    seen = set()
    unique_keywords = []
    for k in combined:
        k_lower = k.lower()
        if k_lower not in seen:
            seen.add(k_lower)
            unique_keywords.append(k)
            
    return ", ".join(unique_keywords[:20])



def update_index_page(latest_title, latest_filename, latest_image):
    if not latest_title or latest_title.strip().lower() in ["test", ""] or len(latest_title.strip()) < 10:
        print(f"WARNING: Refusing to update index.html with invalid/test title: '{latest_title}'")
        all_posts = get_existing_posts()
        valid_posts = [p for p in all_posts if p['file'] != "index.html" and p['title'].strip().lower() not in ["test", ""] and len(p['title'].strip()) >= 10]
        if valid_posts:
            latest_title = valid_posts[0]['title']
            latest_filename = valid_posts[0]['file']
            latest_image = valid_posts[0]['image']
            print(f"Fallback to latest valid post: '{latest_title}' ({latest_filename})")
        else:
            latest_title = "Live Football Coverage & Today's European Football Results"
            latest_filename = "index.html"
            latest_image = "images/hero.webp"

    all_posts = get_existing_posts()
    generate_search_index()
    generate_archive_page()
    
    grid_html = ""
    for p in all_posts[:6]:
        grid_html += f"""
        <div class="news-card">
            <img src="{p['image']}" alt="{html_escape(p['title'])} - GoalPulse" class="news-card-img" loading="lazy" width="130" height="90" onerror="this.onerror=null;this.src='images/hero.webp';">
            <div class="news-card-body">
                <span class="category-tag {p['cat_class']}">{p['cat_name']}</span>
                <a href="{p['file']}" class="news-card-title">{html_escape(p['title'])}</a>
            </div>
        </div>
        """

    sidebar_trending = ""
    for idx, p in enumerate(all_posts[:5], 1):
        sidebar_trending += f"""
        <a href="{p['file']}" class="trending-item">
            <span class="trending-number">{idx}</span>
            <span class="trending-text">{html_escape(p['title'])}</span>
        </a>
        """

    tpl_path = os.path.join(PROJECT_DIR, "templates", "index_template.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        index_html = f.read()

    matches = get_live_matches_data()

    index_html = index_html.replace("{{latest_title}}", html_escape(latest_title))
    title_lang = detect_title_language(latest_title)
    index_html = index_html.replace('lang="en" dir="ltr"',
                                     f'lang="{title_lang}" dir="{("rtl" if title_lang == "ar" else "ltr")}"')
    latest_titles = get_title_translations(latest_title)
    index_html = index_html.replace("{{latest_title_en}}", html_escape(latest_titles["en"]).replace('"', '\\"'))
    index_html = index_html.replace("{{latest_title_fr}}", html_escape(latest_titles["fr"]).replace('"', '\\"'))
    index_html = index_html.replace("{{latest_title_es}}", html_escape(latest_titles["es"]).replace('"', '\\"'))
    index_html = index_html.replace("{{latest_title_ar}}", html_escape(latest_titles["ar"]).replace('"', '\\"'))
    index_html = index_html.replace("{{latest_image}}", html_escape(latest_image))
    index_html = index_html.replace("{{latest_filename}}", latest_filename)
    index_html = index_html.replace("{{grid_html}}", grid_html)
    index_html = index_html.replace("{{sidebar_trending}}", sidebar_trending)
    index_html = index_html.replace("{{top_match_ticker_items}}", get_top_match_ticker_html(matches))
    index_html = index_html.replace("{{modal_matches_html}}", get_modal_matches_html(matches))

    with open(os.path.join(PROJECT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)
    print("Updated index.html successfully.")


def xml_escape(text):
    """Escape text for safe embedding in XML/RSS/sitemap output."""
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") \
                      .replace('"', "&quot;").replace("'", "&apos;")


def _post_pub_iso(post):
    """Return a post's publication ISO-8601 string, with fallback to now."""
    return post.get("pub_iso") or datetime.now().isoformat()


def update_google_news_sitemaps():
    all_posts = get_existing_posts()

    sitemap_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sitemap_xml += f'  <url>\n    <loc>https://gooalpulse.netlify.app/</loc>\n    <lastmod>{datetime.now().strftime("%Y-%m-%d")}</lastmod>\n    <changefreq>hourly</changefreq>\n    <priority>1.0</priority>\n  </url>\n'

    for p in all_posts[:20]:
        if p['file'] != "index.html":
            lastmod = _post_pub_iso(p)[:10]
            sitemap_xml += f"  <url>\n    <loc>https://gooalpulse.netlify.app/{p['file']}</loc>\n    <lastmod>{lastmod}</lastmod>\n    <changefreq>daily</changefreq>\n    <priority>0.8</priority>\n  </url>\n"
    sitemap_xml += '</urlset>'

    with open(os.path.join(PROJECT_DIR, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(sitemap_xml)

    news_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    news_xml += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
    news_xml += '        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">\n'

    for p in all_posts[:10]:
        if p['file'] != "index.html":
            safe_title = xml_escape(p['title'])
            # Per-article publication date (Google News requires the REAL publish date)
            pub_iso = _post_pub_iso(p)
            if len(pub_iso) == 10:
                pub_iso += "T00:00:00+00:00"
            elif "+" not in pub_iso and "Z" not in pub_iso:
                pub_iso += "+00:00"
            news_xml += f"""  <url>
    <loc>https://gooalpulse.netlify.app/{p['file']}</loc>
    <news:news>
      <news:publication>
        <news:name>GoalPulse</news:name>
        <news:language>en</news:language>
      </news:publication>
      <news:publication_date>{pub_iso}</news:publication_date>
      <news:title>{safe_title}</news:title>
    </news:news>
  </url>
"""
    news_xml += '</urlset>'

    with open(os.path.join(PROJECT_DIR, "news_sitemap.xml"), "w", encoding="utf-8") as f:
        f.write(news_xml)


def _format_rfc822(iso_str):
    """Best-effort ISO-8601 -> RFC-822 pubDate conversion for RSS."""
    try:
        from email.utils import format_datetime
        dt = datetime.fromisoformat(str(iso_str).replace("Z", "+00:00"))
        return format_datetime(dt)
    except Exception:
        return datetime.now().strftime("%a, %d %b %Y %H:%M:%S +0000")


def update_rss_feed():
    """Generate the canonical rss.xml feed (linked from every page's <head>)."""
    all_posts = get_existing_posts()

    rss_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    rss_xml += '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/">\n'
    rss_xml += '  <channel>\n'
    rss_xml += '    <title>GoalPulse - Latest Football News</title>\n'
    rss_xml += '    <link>https://gooalpulse.netlify.app/</link>\n'
    rss_xml += '    <atom:link href="https://gooalpulse.netlify.app/rss.xml" rel="self" type="application/rss+xml" />\n'
    rss_xml += '    <description>European football news, live coverage, transfer updates and in-depth analysis from GoalPulse</description>\n'
    rss_xml += '    <language>en</language>\n'
    rss_xml += f'    <lastBuildDate>{_format_rfc822(datetime.now().isoformat())}</lastBuildDate>\n'

    for p in all_posts[:20]:
        if p['file'] != "index.html":
            safe_title = xml_escape(p['title'])
            img_url = get_absolute_image_url(p['image'])
            pub_date = _format_rfc822(_post_pub_iso(p))
            rss_xml += f"""    <item>
      <title>{safe_title}</title>
      <link>https://gooalpulse.netlify.app/{p['file']}</link>
      <guid isPermaLink="true">https://gooalpulse.netlify.app/{p['file']}</guid>
      <pubDate>{pub_date}</pubDate>
      <dc:creator>GoalPulse Editorial Team</dc:creator>
      <description>{safe_title} - Full coverage and analysis on GoalPulse.</description>
      <media:content url="{img_url}" medium="image" width="1200" height="675" />
    </item>
"""
    rss_xml += '</channel>\n</rss>'

    with open(os.path.join(PROJECT_DIR, "rss.xml"), "w", encoding="utf-8") as f:
        f.write(rss_xml)


def update_robots_txt():
    """Regenerate robots.txt referencing every discovery endpoint."""
    robots = (
        "User-agent: *\n"
        "Allow: /\n\n"
        "Sitemap: https://gooalpulse.netlify.app/sitemap.xml\n"
        "Sitemap: https://gooalpulse.netlify.app/news_sitemap.xml\n"
    )
    with open(os.path.join(PROJECT_DIR, "robots.txt"), "w", encoding="utf-8") as f:
        f.write(robots)


def update_google_discover_rss_feed():
    all_posts = get_existing_posts()
    
    rss_xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    rss_xml += '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:media="http://search.yahoo.com/mrss/">\n'
    rss_xml += '  <channel>\n'
    rss_xml += '    <title>GoalPulse - Google Discover Feed</title>\n'
    rss_xml += '    <link>https://gooalpulse.netlify.app/</link>\n'
    rss_xml += '    <description>European football news, live coverage and exclusive stories optimized for Google Discover</description>\n'
    rss_xml += '    <language>en</language>\n'
    
    for p in all_posts[:15]:
        if p['file'] != "index.html":
            safe_title = xml_escape(p['title'])
            img_url = get_absolute_image_url(p['image'])
            rss_xml += f"""    <item>
      <title>{safe_title}</title>
      <link>https://gooalpulse.netlify.app/{p['file']}</link>
      <dc:creator>GoalPulse Editorial Team</dc:creator>
      <description>{safe_title} - Exclusive coverage via GoalPulse.</description>
      <media:content url="{img_url}" medium="image" width="1200" height="675" />
    </item>
"""
    rss_xml += '</channel>\n</rss>'
    
    with open(os.path.join(PROJECT_DIR, "discover_feed.xml"), "w", encoding="utf-8") as f:
        f.write(rss_xml)


def update_netlify_files():
    """Generate Netlify _redirects and _headers in the deploy root (publish = '.').

    These files take precedence over netlify.toml. Missing pages return a REAL
    HTTP 404 (no soft-404 SPA fallback) since every site page is a static file.
    """
    redirects = (
        "# GoalPulse Netlify redirects\n"
        "# All pages are static files served directly by Netlify.\n"
        "# No catch-all rewrite: missing URLs must return a genuine 404 (SEO-safe).\n"
        "/home  /index.html  301\n"
    )
    with open(os.path.join(PROJECT_DIR, "_redirects"), "w", encoding="utf-8") as f:
        f.write(redirects)

    headers = (
        "# GoalPulse Netlify headers\n"
        "/images/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n"
        "/fonts/*\n"
        "  Cache-Control: public, max-age=31536000, immutable\n"
        "/css/*\n"
        "  Cache-Control: public, max-age=86400\n"
        "/*.html\n"
        "  Cache-Control: public, max-age=0, must-revalidate\n"
        "/*.xml\n"
        "  Cache-Control: public, max-age=3600\n"
        "  Content-Type: application/xml; charset=utf-8\n"
    )
    with open(os.path.join(PROJECT_DIR, "_headers"), "w", encoding="utf-8") as f:
        f.write(headers)


def detect_title_language(title):
    """Heuristic: returns 'ar' if the title contains Arabic script, else 'en'."""
    if not title:
        return "en"
    return "ar" if re.search(r"[\u0600-\u06FF]", title) else "en"


def get_title_translations(title):
    if GEMINI_API_KEY:
        try:
            import urllib.request
            import json
            prompt = (
                f"Translate the following football headline into 4 languages: English, French, Spanish, Arabic.\n"
                f"Headline: \"{title}\"\n"
                f"Respond ONLY with valid JSON with keys: \"en\", \"fr\", \"es\", \"ar\". No extra text or markdown formatting."
            )
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={GEMINI_API_KEY}"
            payload = json.dumps({"contents": [{"parts": [{"text": prompt}]}]}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                text = res["candidates"][0]["content"]["parts"][0]["text"].strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
                parsed = json.loads(text)
                if all(k in parsed for k in ["en", "fr", "es", "ar"]):
                    return parsed
        except Exception as e:
            print("Title translation via Gemini failed:", e)

    detected = detect_title_language(title)
    if detected == "ar":
        return {"en": "European Football — Trending Coverage", "fr": "Football Européen — Couverture", "es": "Fútbol Europeo — Cobertura", "ar": title}
    return {"en": title, "fr": title, "es": title, "ar": "تغطية كروية أوروبية حصرية"}


def build_article_page():
    cleanup_old_articles()
    
    title, source = fetch_top_trending_news()
    
    if is_too_similar_to_recent_posts(title, threshold=0.70):
        print("Publishing run skipped: Topic was already covered recently (classic dedup).")
        return

    ai_dup = is_duplicate_via_ai(title)
    if ai_dup is True:
        print("Publishing run skipped: Topic flagged as SEMANTIC DUPLICATE by AI dedup.")
        return

    slug = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"post_{slug}.html"
    article_url = f"https://gooalpulse.netlify.app/{filename}"
    date_str = datetime.now().strftime("%Y-%m-%d")
    iso_date = datetime.now().isoformat()
    seo_keywords = generate_seo_keywords(title)

    image_url, image_attribution = fetch_pexels_image(title, slug)

    matches_data = get_live_matches_data()
    article_body = generate_deep_1200_words_article(title, matches_data)
    all_posts = get_existing_posts()

    sidebar_items = ""
    for idx, p in enumerate(all_posts[:5], 1):
        sidebar_items += f"""
        <a href="{p['file']}" class="trending-item">
            <span class="trending-number">{idx}</span>
            <span class="trending-text">{html_escape(p['title'])}</span>
        </a>
        """

    tpl_path = os.path.join(PROJECT_DIR, "templates", "article_template.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        article_html = f.read()

    titles = get_title_translations(title)
    title_lang = detect_title_language(title)
    article_html = article_html.replace('lang="en" dir="ltr"',
                                         f'lang="{title_lang}" dir="{("rtl" if title_lang == "ar" else "ltr")}"')
    article_html = article_html.replace("{{title}}", html_escape(title))
    article_html = article_html.replace("{{title_json}}", json.dumps(str(title), ensure_ascii=False))
    article_html = article_html.replace("{{title_en}}", js_string_escape(titles["en"]))
    article_html = article_html.replace("{{title_fr}}", js_string_escape(titles["fr"]))
    article_html = article_html.replace("{{title_es}}", js_string_escape(titles["es"]))
    article_html = article_html.replace("{{title_ar}}", js_string_escape(titles["ar"]))
    article_html = article_html.replace("{{filename}}", filename)
    article_html = article_html.replace("{{date_str}}", date_str)
    article_html = article_html.replace("{{iso_date}}", iso_date)
    article_html = article_html.replace("{{seo_keywords}}", seo_keywords)
    article_html = article_html.replace("{{source}}", source)
    article_html = article_html.replace("{{image_url}}", html_escape(image_url))
    article_html = article_html.replace("{{absolute_image_url}}", get_absolute_image_url(image_url))
    article_html = article_html.replace("{{image_attribution}}", image_attribution)
    article_html = article_html.replace("{{article_body}}", article_body)
    article_html = article_html.replace("{{related_articles}}", build_related_articles_html(all_posts, filename))
    article_html = article_html.replace("{{sidebar_items}}", sidebar_items)
    match_center_cards = get_modal_matches_html(matches_data)
    article_html = article_html.replace("{{match_center_cards}}", match_center_cards)
    article_html = article_html.replace("{{top_match_ticker_items}}", get_top_match_ticker_html(matches_data))
    article_html = article_html.replace("{{modal_matches_html}}", match_center_cards)

    with open(os.path.join(PROJECT_DIR, filename), "w", encoding="utf-8") as f:
        f.write(article_html)
        
    print(f"Generated Article: {filename}")
    try:
        update_index_page(title, filename, image_url)
    except Exception as e:
        print("Index page update failed (non-fatal):", e)
    for updater in (update_google_news_sitemaps, update_rss_feed,
                    update_google_discover_rss_feed, update_robots_txt,
                    update_netlify_files):
        try:
            updater()
        except Exception as e:
            print(f"{updater.__name__} failed (non-fatal):", e)
    
    send_telegram_notification(title, article_url, image_url)
    
    try:
        import indexer
        indexer.notify_search_engines(article_url)
    except Exception as e:
        print("Indexer notification error:", e)

if __name__ == "__main__":
    assert clean_headline("Manchester United sign new striker - BBC.com") == "Manchester United sign new striker"
    assert clean_headline("Real Madrid win Champions League - Marca.com") == "Real Madrid win Champions League"
    assert clean_headline("Arsenal beat Liverpool in Premier League thriller") == "Arsenal beat Liverpool in Premier League thriller"
    print("clean_headline unit tests passed successfully.")
    build_article_page()


def rebuild_all_existing():
    """Re-render every existing post_*.html with the updated article_template,
    fixing lang/dir, ads placement and adding the breaking + match ticker bars.
    Preserves the original article body and metadata; only the wrapper is rewritten."""
    pattern = os.path.join(PROJECT_DIR, "post_*.html")
    files = sorted(glob.glob(pattern), reverse=True)
    if not files:
        print("No post_*.html files to rebuild.")
        return

    tpl_path = os.path.join(PROJECT_DIR, "templates", "article_template.html")
    with open(tpl_path, "r", encoding="utf-8") as f:
        template_src = f.read()

    rebuilt = 0
    posts_for_index = []
    for fpath in files:
        filename = os.path.basename(fpath)
        try:
            with open(fpath, "r", encoding="utf-8") as fp:
                old = fp.read()
        except Exception:
            continue

        m_title = re.search(r'<title>(.*?)\|', old)
        if not m_title:
            continue
        title = m_title.group(1).strip()
        m_img = re.search(r'class="hero-img"[^>]*?\ssrc="(.*?)"', old)
        if not m_img:
            m_img = re.search(r'src="(.*?)"[^>]*?class="hero-img"', old)
        image_url = m_img.group(1) if m_img else "images/hero.webp"
        m_iso = re.search(r'datetime="([^"]+)"', old)
        iso_date = m_iso.group(1) if m_iso else "2026-07-31T00:00:00"
        m_date = re.search(r'<time[^>]*>([^<]+)</time>', old)
        date_str = m_date.group(1) if m_date else iso_date[:10]
        m_src = re.search(r'<span data-i18n="meta_source">.*?<strong>(.*?)</strong>', old, re.DOTALL)
        source = "GoalPulse Editorial Desk"
        if m_src:
            try:
                source = re.search(r'M[الصدرource]{0,8}:\s*([^<]+)', m_src.group(1)).group(1).strip()
            except Exception:
                pass

        body_match = re.search(
            r'(<article class="main-content".*?>)(.*?)(</article>)',
            old, re.DOTALL | re.IGNORECASE
        )
        legacy_container_match = None
        legacy_body_match = None
        if not body_match:
            legacy_container_match = re.search(
                r'(<div class="container"[^>]*>)(.*?)(</div>\s*<footer|\Z)',
                old, re.DOTALL | re.IGNORECASE
            )
        if not body_match and not legacy_container_match:
            legacy_body_match = re.search(
                r'(<body[^>]*>)(.*?)(</body>)',
                old, re.DOTALL | re.IGNORECASE
            )
        if body_match:
            article_body = body_match.group(2)
        elif legacy_container_match:
            article_body = legacy_container_match.group(2)
        elif legacy_body_match:
            article_body = legacy_body_match.group(2)
        else:
            article_body = ""

        # Extract only the inner-body content (between the hero image and the </article>),
        # stripping the legacy top Adsterra banner block, image_attribution wrapper and any
        # inline ad_container-728 we have replaced with {ad_banner_*} tokens.
        inner_segments = []
        saw_hero = False
        for line in article_body.splitlines():
            stripped = line.strip()
            if 'hero-img' in stripped or ('class="container"' in stripped and legacy_container_match) or ('<header' in stripped and legacy_body_match):
                saw_hero = True
                continue
            if not saw_hero:
                continue
            if '<figcaption' in stripped and '</figcaption>' in stripped:
                continue
            if 'atOptions' in stripped:
                continue
            if 'highperformanceformat.com' in stripped:
                continue
            if 'effectivecpmnetwork.com' in stripped:
                continue
            if 'container-e0506d6c367e6bb36b482997b233ed58' in stripped:
                continue
            if 'pl30532744.effectivecpmnetwork.com' in stripped:
                continue
            if 'pl30532743.effectivecpmnetwork.com' in stripped:
                continue
            if 'class="ad-container-728"' in stripped and 'data-i18n="ad_label"' not in stripped:
                continue
            if 'ad-after-content' in stripped:
                continue
            if 'ad-container-728 ad-after-content' in stripped:
                continue
            if 'class="ad-container"' in stripped and 'data-i18n="ad_label"' not in stripped:
                continue
            if 'class="ad-slot"' in stripped:
                continue
            if 'class="source-link"' in stripped:
                continue
            if '<div class="ad-sep"' in stripped:
                continue
            if '</div>' == stripped and 'ad-after-content' in ''.join(inner_segments[-3:]):
                continue
            if '</article>' in stripped:
                break
            if legacy_container_match and re.match(r'\s*</div>\s*$', stripped):
                break
            if legacy_body_match and ('</body>' in stripped or '<footer' in stripped):
                break
            inner_segments.append(line)
        body_html = "\n".join(inner_segments).strip()
        body_html = re.sub(
            r'<!-- End-of-article Sponsor[\s\S]*?<!-- /End-of-article Sponsor -->',
            '', body_html, flags=re.IGNORECASE
        )
        body_html = re.sub(
            r'<div class="ad-container-728 ad-after-content"[\s\S]*?</script>\s*</div>',
            '', body_html, flags=re.IGNORECASE
        )
        body_html = re.sub(
            r'<div class="ad-container-728 ad-after-content"[\s\S]*?</div>\s*</div>',
            '', body_html, flags=re.IGNORECASE
        )
        # Strip inner inline ad-container-728 blocks that wrap sponsor banners
        body_html = re.sub(
            r'<div class="ad-container-728"[^>]*>[\s\S]*?</script>\s*</div>',
            '', body_html, flags=re.IGNORECASE
        )
        if not body_html:
            continue

        html = template_src
        title_lang = detect_title_language(title)
        titles = get_title_translations(title)
        html = html.replace('lang="en" dir="ltr"',
                             f'lang="{title_lang}" dir="{("rtl" if title_lang == "ar" else "ltr")}"')
        html = html.replace("{{title}}", html_escape(title))
        html = html.replace("{{title_en}}", html_escape(titles["en"]).replace('"', '\\"'))
        html = html.replace("{{title_fr}}", html_escape(titles["fr"]).replace('"', '\\"'))
        html = html.replace("{{title_es}}", html_escape(titles["es"]).replace('"', '\\"'))
        html = html.replace("{{title_ar}}", html_escape(titles["ar"]).replace('"', '\\"'))
        html = html.replace("{{filename}}", filename)
        html = html.replace("{{date_str}}", date_str)
        html = html.replace("{{iso_date}}", iso_date)
        html = html.replace("{{seo_keywords}}", generate_seo_keywords(title))
        html = html.replace("{{source}}", source)
        html = html.replace("{{image_url}}", html_escape(image_url))
        html = html.replace("{{absolute_image_url}}", get_absolute_image_url(image_url))
        html = html.replace("{{image_attribution}}", "")
        html = html.replace("{{article_body}}", body_html)
        html = html.replace("{{related_articles}}", build_related_articles_html(get_existing_posts(), filename))
        sidebar_items = ""
        all_posts = get_existing_posts()
        for idx, p in enumerate(all_posts[:5], 1):
            sidebar_items += f"""
            <a href="{p['file']}" class="trending-item">
                <span class="trending-number">{idx}</span>
                <span class="trending-text">{p['title']}</span>
            </a>
            """
        html = html.replace("{{sidebar_items}}", sidebar_items)
        matches_data = get_live_matches_data()
        html = html.replace("{{top_match_ticker_items}}", get_top_match_ticker_html(matches_data))
        html = html.replace("{{modal_matches_html}}", get_modal_matches_html(matches_data))
        html = html.replace("{{match_center_cards}}", get_modal_matches_html(matches_data))
        # Clear any leftover placeholders that may have survived (e.g. when keys absent)
        html = html.replace("{{title_en}}", html_escape(title)).replace("{{title_fr}}", html_escape(title))
        html = html.replace("{{title_es}}", html_escape(title)).replace("{{title_ar}}", html_escape(title))

        with open(fpath, "w", encoding="utf-8") as fp:
            fp.write(html)
        rebuilt += 1
        posts_for_index.append({"title": title, "file": filename, "image": image_url})

    print(f"Rebuilt {rebuilt} article(s) with updated template.")
    if posts_for_index:
        latest = posts_for_index[0]
        update_index_page(latest["title"], latest["file"], latest["image"])
    for updater in (update_google_news_sitemaps, update_rss_feed,
                    update_google_discover_rss_feed, update_robots_txt,
                    update_netlify_files):
        try:
            updater()
        except Exception as e:
            print(f"{updater.__name__} failed (non-fatal):", e)
