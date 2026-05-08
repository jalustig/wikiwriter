# ABOUTME: Tests fetch_readable against a list of citation URLs from Wikipedia articles.
# ABOUTME: Reports per-domain success/failure stats and saves a detailed log.

import asyncio
import sys
import os
import time
import json
from urllib.parse import urlparse
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.fetcher import fetch_readable

URLS_FILE = os.path.join(os.path.dirname(__file__), "citation_urls.txt")
RESULTS_FILE = os.path.join(os.path.dirname(__file__), "fetch_results.json")

# Limit for quick testing; set to None for full run
MAX_URLS = int(os.environ.get("MAX_URLS", "50"))

# Max concurrent fetches (stay polite)
CONCURRENCY = 3


def load_urls() -> list[str]:
    with open(URLS_FILE) as f:
        return [line.strip() for line in f if line.strip()]


def classify_result(text: str, error: str | None) -> str:
    if error:
        if "captcha" in error.lower() or "blocked" in error.lower():
            return "blocked"
        if "timeout" in error.lower():
            return "timeout"
        if "404" in error or "not found" in error.lower():
            return "not_found"
        return "error"
    if not text or len(text) < 100:
        return "empty"
    return "success"


async def fetch_one(url: str, sem: asyncio.Semaphore) -> dict:
    async with sem:
        start = time.monotonic()
        text = None
        error = None
        try:
            text = await fetch_readable(url)
        except Exception as e:
            error = str(e)
        elapsed = time.monotonic() - start
        status = classify_result(text or "", error)
        domain = urlparse(url).netloc
        result = {
            "url": url,
            "domain": domain,
            "status": status,
            "elapsed": round(elapsed, 2),
            "chars": len(text) if text else 0,
            "error": error,
        }
        icon = {"success": "✓", "empty": "~", "blocked": "✗", "timeout": "⏱", "not_found": "404", "error": "!"}.get(status, "?")
        print(f"  {icon} [{elapsed:5.1f}s] {status:10s} {domain} — {url[:80]}")
        return result


async def main():
    all_urls = load_urls()
    urls = all_urls[:MAX_URLS] if MAX_URLS else all_urls
    print(f"Testing {len(urls)} URLs (of {len(all_urls)} total) with concurrency={CONCURRENCY}\n")

    sem = asyncio.Semaphore(CONCURRENCY)
    results = await asyncio.gather(*[fetch_one(u, sem) for u in urls])

    # Summary by status
    by_status: dict[str, int] = defaultdict(int)
    by_domain: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        by_status[r["status"]] += 1
        by_domain[r["domain"]][r["status"]] += 1

    print(f"\n{'='*60}")
    print("SUMMARY BY STATUS:")
    for status, count in sorted(by_status.items(), key=lambda x: -x[1]):
        pct = count / len(results) * 100
        print(f"  {status:12s} {count:4d}  ({pct:.0f}%)")

    print(f"\nTOP DOMAINS BY FAILURE:")
    failed_domains = [(d, counts) for d, counts in by_domain.items() if counts.get("error", 0) + counts.get("blocked", 0) + counts.get("timeout", 0) > 0]
    failed_domains.sort(key=lambda x: -(x[1].get("error", 0) + x[1].get("blocked", 0) + x[1].get("timeout", 0)))
    for domain, counts in failed_domains[:15]:
        fail_count = counts.get("error", 0) + counts.get("blocked", 0) + counts.get("timeout", 0)
        total = sum(counts.values())
        print(f"  {domain:40s} {fail_count}/{total} failed")

    with open(RESULTS_FILE, "w") as f:
        json.dump(list(results), f, indent=2)
    print(f"\nDetailed results saved to {RESULTS_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
