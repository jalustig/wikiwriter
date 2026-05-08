# ABOUTME: Extracts all external citation URLs from specified Wikipedia articles.
# ABOUTME: Writes one URL per line to a flat file for use by fetch testing scripts.

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.wikipedia import fetch_article

ARTICLES = [
    "https://en.wikipedia.org/wiki/Judaism",
    "https://en.wikipedia.org/wiki/Transformer_(deep_learning)",
]

OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "citation_urls.txt")


async def main():
    urls: list[str] = []
    for article_url in ARTICLES:
        print(f"Fetching citations from: {article_url}")
        article = await fetch_article(article_url)
        article_urls = [c.url for c in article.citations]
        print(f"  Found {len(article_urls)} citations")
        urls.extend(article_urls)

    # Deduplicate while preserving order
    seen: set[str] = set()
    unique_urls = [u for u in urls if not (u in seen or seen.add(u))]

    with open(OUTPUT_FILE, "w") as f:
        for url in unique_urls:
            f.write(url + "\n")

    print(f"\nWrote {len(unique_urls)} unique URLs to {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
