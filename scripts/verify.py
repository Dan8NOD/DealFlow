"""hermes-verify-render-portal.py — ad-hoc verification for Render-deployed FastAPI portals.

Pattern: login, hit each API endpoint, verify expected behavior. Self-cleans.
Use when you don't have a pytest suite and need to confirm a deploy works.

Usage:
    python3 verify-render-portal.py \
        --base-url https://renter-portal-1-jajv.onrender.com \
        --email dancruzhomes@gmail.com --password 'Leads2025!'

The script always logs in first (most endpoints require auth) and reports
each check as PASS/FAIL with details.

Note: this is ad-hoc, NOT a test suite. Treat failures as a signal to dig
deeper, not as a green/red build status.
"""

import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_BASE_URL = os.environ.get("RENDER_URL", "https://renter-portal-1-jajv.onrender.com")
DEFAULT_EMAIL = os.environ.get("RENDER_EMAIL", "dancruzhomes@gmail.com")
DEFAULT_PASSWORD = os.environ.get("RENDER_PASSWORD", "Leads2025!")


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base-url", default=DEFAULT_BASE_URL)
    p.add_argument("--email", default=DEFAULT_EMAIL)
    p.add_argument("--password", default=DEFAULT_PASSWORD)
    return p.parse_args()


def main():
    args = parse_args()
    base = args.base_url.rstrip("/")
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    ua = {"User-Agent": "hermes-verify", "Cache-Control": "no-cache"}

    results = []

    def check(name, fn):
        try:
            ok, info = fn()
        except Exception as e:
            ok, info = False, f"EXC: {type(e).__name__}: {str(e)[:100]}"
        results.append((name, ok, info))
        print(f"  {'PASS' if ok else 'FAIL'}: {name} -- {info}")

    def get(path):
        req = urllib.request.Request(f"{base}{path}", headers=ua)
        return opener.open(req)

    def status_of(path):
        try:
            return get(path).status
        except urllib.error.HTTPError as e:
            return e.code
        except Exception:
            return -1

    # --- 1. Login ---
    print("\n=== Login ===")
    login_data = urllib.parse.urlencode({"email": args.email, "password": args.password}).encode()
    req = urllib.request.Request(
        f"{base}/auth/login",
        data=login_data,
        headers={**ua, "Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        r = opener.open(req)
        check("login", lambda: (r.status == 200 and ("/dashboard" in r.url or "/nod" in r.url),
                                f"status={r.status} url={r.url}"))
    except urllib.error.HTTPError as e:
        check("login", lambda: (False, f"HTTP {e.code}"))
        sys.exit(1)

    # --- 2. Health ---
    print("\n=== Health ===")
    try:
        r = urllib.request.urlopen(urllib.request.Request(f"{base}/health", headers=ua))
        body = r.read()
        check("/health", lambda: (r.status == 200 and b"ok" in body, f"status={r.status}"))
    except Exception as e:
        check("/health", lambda: (False, f"EXC {e}"))

    # --- 3. Dashboard renders ---
    print("\n=== Dashboard ===")
    r = get("/dashboard")
    body = r.read().decode()
    check("dashboard HTML", lambda: (r.status == 200 and len(body) > 1000, f"size={len(body)}"))

    # --- 4. Public contact form ---
    print("\n=== Public /contact ===")
    r = urllib.request.urlopen(urllib.request.Request(
        f"{base}/contact?source=youtube", headers=ua))
    body = r.read().decode()
    has_source = 'value="youtube"' in body
    check("/contact renders source tag", lambda: (has_source, f"has_source={has_source}"))

    # --- 5. Manual API: /api/leads ---
    print("\n=== API: /api/leads ===")
    r = get("/api/leads?limit=10")
    leads = json.loads(r.read())
    check("/api/leads returns data",
          lambda: (isinstance(leads, list) and len(leads) > 0, f"got {len(leads)} leads"))

    # --- 6. Dashboard JSON stats ---
    print("\n=== API: /api/dashboard.json ===")
    r = get("/api/dashboard.json")
    data = json.loads(r.read())
    stats = data.get("stats", {})
    check("/api/dashboard.json stats populated",
          lambda: (stats.get("active_leads", 0) > 0,
                   f"active_leads={stats.get('active_leads')} pipeline={stats.get('in_pipeline')}"))

    # --- 7. Public POST: /api/leads-from-landing ---
    print("\n=== Public lead capture ===")
    test_email = f"verify-{int(time.time())}@test.local"
    payload = {"name": "Verify Bot", "email": test_email, "source": "Verify", "notes": "ad-hoc verify"}
    req = urllib.request.Request(
        f"{base}/api/leads-from-landing",
        data=json.dumps(payload).encode(),
        headers={**ua, "Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req)
    resp = json.loads(r.read())
    check("POST /api/leads-from-landing (public)",
          lambda: (resp.get("ok") is True and resp.get("id"),
                   f"created={resp.get('ok')} id={resp.get('id')}"))

    # --- 8. Confirm test lead landed in DB ---
    print("\n=== Verify test lead in DB ===")
    r = get("/api/leads?limit=200")
    leads = json.loads(r.read())
    found = next((l for l in leads if l.get("email") == test_email), None)
    check("test lead found via /api/leads",
          lambda: (found is not None and found.get("source") == "Verify",
                   f"found={found is not None} source={found and found.get('source')}"))

    # --- Summary ---
    print("\n=== SUMMARY ===")
    passed = sum(1 for _, ok, _ in results if ok)
    total = len(results)
    print(f"  {passed}/{total} checks passed")
    for name, ok, info in results:
        print(f"    [{'PASS' if ok else 'FAIL'}] {name}")

    print(f"\n# Note: test lead id={resp.get('id')} created -- delete via dashboard if undesired")
    print("# ad-hoc verification only -- not a test suite")
    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()