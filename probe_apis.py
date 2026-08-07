"""Probe every external API the GoalPulse pipeline depends on and print a clear
PASS/FAIL report. Reads keys from environment variables matching publisher.py."""
import os
import sys
import json
import time
import urllib.parse
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import publisher  # noqa: E402

PASS = "\033[92mPASS\033[0m"
FAIL = "\033[91mFAIL\033[0m"
WARN = "\033[93mWARN\033[0m"


def banner(title):
    print("\n" + "=" * 60)
    print("  " + title)
    print("=" * 60)


def http_get(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            return r.status, body, round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return e.code, "", round(time.time() - t0, 2)
    except Exception as e:
        return 0, str(e), round(time.time() - t0, 2)


def http_post_json(url, payload, headers=None, timeout=25, api_key_in_url=None):
    full_url = url if not api_key_in_url else url + api_key_in_url
    data = json.dumps(payload).encode("utf-8")
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(full_url, data=data, headers=h, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", errors="replace")
            return r.status, body, round(time.time() - t0, 2)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace"), round(time.time() - t0, 2)
    except Exception as e:
        return 0, str(e), round(time.time() - t0, 2)


def test_google_news_rss():
    banner("1) Google News RSS (news discovery)")
    q = "Premier League breaking transfer news"
    rss_url = f"https://news.google.com/rss/search?q={urllib.parse.quote(q)}&hl=en&gl=GB&ceid=GB:en"
    status, body, dt = http_get(rss_url, timeout=15)
    entries = body.count("<item>") if body else 0
    if status == 200 and entries > 0:
        print(f"  {PASS} status=200  entries={entries}  time={dt}s")
        title = publisher.clean_headline(body.split("<title>")[2].split("</title>")[0]
                                          if "<title>" in body else "")
        print(f"       sample title: {title[:70]}")
        return True
    print(f"  {FAIL} status={status}  entries={entries}  time={dt}s")
    if body:
        print(f"       body[:200]: {body[:200]}")
    return False


def test_gemini_article_and_translation():
    banner("2) Gemini API (article generation + title translation)")
    key = os.environ.get("GEMINI_API_KEY") or publisher.GEMINI_API_KEY
    if not key:
        print(f"  {WARN} GEMINI_API_KEY not set — skipped (publisher falls back gracefully)")
        return None
    title = "Real Madrid beats Barcelona in El Clasico thriller"
    # Article generation
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-flash-latest:generateContent?key={key}"
    payload = {"contents": [{"parts": [{"text": f"Write a 300-word English news article about: {title}"}]}]}
    st, body, dt = http_post_json(url, payload, timeout=30)
    if st != 200:
        print(f"  {FAIL} generation  status={st}  time={dt}s  body={body[:200]}")
        return False
    try:
        gen = json.loads(body)["candidates"][0]["content"]["parts"][0]["text"]
        print(f"  {PASS} generation  status=200  chars={len(gen)}  time={dt}s")
    except Exception as e:
        print(f"  {FAIL} could not parse generation response: {e}")
        return False
    # Translation
    tr = publisher.get_title_translations(title)
    if tr and all(k in tr for k in ["en", "fr", "es", "ar"]):
        print(f"  {PASS} translation  keys={list(tr.keys())}  ar={tr['ar'][:40]}")
        return True
    print(f"  {FAIL} translation incomplete: {tr}")
    return False


def test_pexels():
    banner("3) Pexels API (image fetch)")
    key = os.environ.get("PEXELS_API_KEY") or publisher.PEXELS_API_KEY
    if not key:
        print(f"  {WARN} PEXELS_API_KEY not set — skipped (Wikimedia fallback is active)")
        return None
    url = "https://api.pexels.com/v1/search?query=real%20madrid&per_page=3"
    st, body, dt = http_get(url, headers={"Authorization": key}, timeout=15)
    if st == 200:
        try:
            n = len(json.loads(body).get("photos", []))
            print(f"  {PASS} status=200  photos={n}  time={dt}s")
            return n > 0
        except Exception:
            print(f"  {FAIL} invalid json body (len={len(body)})")
            return False
    print(f"  {FAIL} status={st}  time={dt}s  body={body[:200]}")
    return False


def test_wikimedia_commons():
    banner("4) Wikimedia Commons (no-key image fallback)")
    res = publisher.fetch_wikimedia_image("Real Madrid Champions League", f"probe_{int(time.time())}")
    cache_path = os.path.join(publisher.GENERATED_IMG_DIR, res[0].split("/")[-1])
    ok = res[0].startswith("images/generated/") and os.path.exists(cache_path)
    if ok:
        print(f"  {PASS} downloaded {res[0]} ({os.path.getsize(cache_path)} bytes)")
        try:
            os.remove(cache_path)
        except Exception:
            pass
        return True
    print(f"  {WARN} returned local fallback: {res[0]} (Wikimedia unreachable — local pool used)")
    return None


def test_api_football():
    banner("5) API-Football (live fixtures)")
    key = os.environ.get("FOOTBALL_API_KEY") or publisher.FOOTBALL_API_KEY
    if not key:
        print(f"  {WARN} FOOTBALL_API_KEY not set — matches will show 'no live matches'")
        return None
    from datetime import datetime
    today = datetime.utcnow().strftime("%Y-%m-%d")
    url = f"https://v3.football.api-sports.io/fixtures?date={today}"
    st, body, dt = http_get(url, headers={"x-apisports-key": key}, timeout=15)
    if st == 200:
        try:
            n = len(json.loads(body).get("response", []))
            print(f"  {PASS} status=200  fixtures_today={n}  time={dt}s")
            return n >= 0
        except Exception:
            print(f"  {FAIL} invalid json body")
            return False
    print(f"  {FAIL} status={st}  time={dt}s  body={body[:200]}")
    return False


def test_telegram():
    banner("6) Telegram Bot (getMe probe — does not send spam)")
    token = os.environ.get("TELEGRAM_TOKEN") or publisher.TELEGRAM_TOKEN
    if not token:
        print(f"  {WARN} TELEGRAM_TOKEN not set — skipped")
        return None
    url = f"https://api.telegram.org/bot{token}/getMe"
    st, body, dt = http_get(url, timeout=12)
    if st == 200 and '"ok":true' in body:
        try:
            uname = json.loads(body)["result"]["username"]
            print(f"  {PASS} status=200  bot=@{uname}  time={dt}s")
            return True
        except Exception:
            print(f"  {PASS} (status=200) but parse failed")
            return True
    print(f"  {FAIL} status={st}  time={dt}s  body={body[:200]}")
    return False


def test_indexnow():
    banner("7) IndexNow endpoint reachability (no submit unless configured)")
    # Just check the endpoint responds — submitting a real URL would need a key file on root.
    url = "https://api.indexnow.org/indexnow?url=https://gooalpulse.netlify.app/&key=test"
    st, body, dt = http_get(url, timeout=12)
    # IndexNow returns 200/202/400/422 — 200/202 OK, anything else informational.
    if st in (200, 202):
        print(f"  {PASS} status={st}  time={dt}s  (endpoint reachable)")
        return True
    if st in (400, 422):
        print(f"  {PASS} endpoint reachable but rejected dummy key: status={st} (expected for unverified key)")
        return True
    print(f"  {FAIL} status={st}  time={dt}s  body={body[:120]}")
    return False


if __name__ == "__main__":
    results = {
        "Google News RSS": test_google_news_rss(),
        "Gemini": test_gemini_article_and_translation(),
        "Pexels": test_pexels(),
        "Wikimedia Commons": test_wikimedia_commons(),
        "API-Football": test_api_football(),
        "Telegram Bot": test_telegram(),
        "IndexNow": test_indexnow(),
    }
    banner("SUMMARY")
    for name, ok in results.items():
        status = PASS if ok is True else (WARN if ok is None else FAIL)
        note = "OK" if ok is True else ("SKIPPED (no key)" if ok is None else "FAILED")
        print(f"  {status}  {name:25s} {note}")
