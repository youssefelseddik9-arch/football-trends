"""
Google Indexing API integration for GoalPulse.

Notifies Google (Indexing API v3), Bing and Yandex (IndexNow) the instant a new
article is published so that search engines can crawl it within minutes instead
of waiting for the normal discovery cycle.

Usage (from publisher or any other script):

    from indexer import notify_search_engines
    notify_search_engines("https://gooalpulse.netlify.app/post_20260731171700.html")

Or directly:

    from indexer import index_url
    index_url("https://gooalpulse.netlify.app/post_20260731171700.html")

The service-account credentials must live at ./service_account.json next to this
file.  The file is git-ignored.  In CI it can be injected from a base64-encoded
GitHub secret named ENCRYPTED_SERVICE_ACCOUNT (see .github/workflows).
"""

import os
import sys
import json
import requests

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
SERVICE_ACCOUNT_PATH = os.path.join(PROJECT_DIR, "service_account.json")

SITE_HOST = "gooalpulse.netlify.app"
INDEXNOW_KEY = "gooalpulse-indexnow-key-2026"

# Indexing API scope and endpoint
INDEXING_SCOPE = "https://www.googleapis.com/auth/indexing"
INDEXING_ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"


def _get_access_token():
    """Obtain an OAuth2 access token from the service-account JSON file.

    Returns None if credentials are missing or invalid (logged to stderr).
    """
    if not os.path.exists(SERVICE_ACCOUNT_PATH):
        print("[indexer] service_account.json not found -> Google Indexing API disabled.")
        print("         Place the JSON key at:", SERVICE_ACCOUNT_PATH)
        return None
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request
    except ImportError:
        print("[indexer] google-auth libraries not installed -> install google-auth google-auth-httplib2")
        return None

    try:
        credentials = service_account.Credentials.from_service_account_file(
            SERVICE_ACCOUNT_PATH, scopes=[INDEXING_SCOPE]
        )
        credentials.refresh(Request())
        return credentials.token
    except Exception as exc:
        print(f"[indexer] Failed to obtain OAuth token: {exc}")
        return None


def index_url(url, notification_type="URL_UPDATED"):
    """Submit a single URL to the Google Indexing API v3.

    Args:
        url: full public URL of the newly published/deleted page.
        notification_type: "URL_UPDATED" (default) or "URL_DELETED".

    Returns:
        (status_code, response_body) tuple, or (None, None) if disabled.
    """
    token = _get_access_token()
    if not token:
        return None, None

    payload = {"url": url, "type": notification_type}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }

    try:
        resp = requests.post(INDEXING_ENDPOINT, headers=headers, json=payload, timeout=20)
        if resp.status_code == 200:
            print(f"[Google Indexing API] Successfully requested indexing for: {url}")
            try:
                body = resp.json()
                notify_time = body.get("urlNotificationMetadata", {}).get("latestUpdate", {}).get("notifyTime")
                if notify_time:
                    print(f"[Google Indexing API] Notify time: {notify_time}")
            except Exception:
                body = resp.text
        elif resp.status_code == 403:
            print(f"[Google Indexing API] HTTP 403 for {url} - Permission denied / URL ownership not verified.")
            print("[Google Indexing API] ACTION REQUIRED:")
            print("  1. Open Google Search Console: https://search.google.com/search-console")
            print("  2. Add the service-account email as an owner of the site property:")
            print(f"     {os.path.exists(SERVICE_ACCOUNT_PATH) and __import__('json').load(open(SERVICE_ACCOUNT_PATH, encoding='utf-8'))['client_email'] or '(service_account.json missing)'}")
            print(f"  3. Verify ownership of {SITE_HOST} (DNS TXT or HTML tag).")
            print("[Google Indexing API] Continuing - this does not block article publication.")
            body = resp.text
        else:
            print(f"[Google Indexing API] HTTP {resp.status_code} for {url}")
            print(f"[Google Indexing API] Response: {resp.text}")
            body = resp.text
        return resp.status_code, body
    except Exception as exc:
        print(f"[Google Indexing API] Request failed for {url}: {exc}")
        return None, str(exc)


def _notify_indexnow(article_url):
    """Notify Bing & Yandex via the IndexNow protocol (no auth required)."""
    payload = {
        "host": SITE_HOST,
        "key": INDEXNOW_KEY,
        "keyLocation": f"https://{SITE_HOST}/{INDEXNOW_KEY}.txt",
        "urlList": [article_url, f"https://{SITE_HOST}/"],
    }
    try:
        resp = requests.post("https://api.indexnow.org/indexnow", json=payload, timeout=10)
        if resp.status_code in [200, 202]:
            print(f"[IndexNow] Successfully notified Bing & Yandex of: {article_url}")
        else:
            print(f"[IndexNow] HTTP {resp.status_code}: {resp.text}")
    except Exception as exc:
        print(f"[IndexNow] Notification error: {exc}")


def notify_search_engines(article_url):
    """Convenience entry point called by publisher.py after publishing an article.

    Calls both the Google Indexing API and IndexNow (Bing/Yandex).  Failures in
    either channel are logged but never raise, so the publishing pipeline keeps
    running.
    """
    print(f"=== Starting Instant Search Engine Indexing for: {article_url} ===")

    # 1. Google Indexing API (direct crawl request)
    try:
        status, _ = index_url(article_url, "URL_UPDATED")
        if status == 200:
            print("[indexer] Google Indexing API: OK")
        elif status is None:
            print("[indexer] Google Indexing API: DISABLED (no credentials) - skipping.")
        else:
            print(f"[indexer] Google Indexing API: returned status {status}")
    except Exception as exc:
        print(f"[indexer] Google Indexing API error (non-fatal): {exc}")

    # 2. IndexNow (Bing + Yandex)
    _notify_indexnow(article_url)

    print("=== Instant Indexing routine completed ===")


if __name__ == "__main__":
    # CLI: python indexer.py https://gooalpulse.netlify.app/post_xxx.html
    if len(sys.argv) > 1:
        target = sys.argv[1]
    else:
        # Default to homepage
        target = f"https://{SITE_HOST}/"
    notify_search_engines(target)
