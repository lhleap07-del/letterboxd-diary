#!/usr/bin/env python3
"""Export the user's entire public Letterboxd Films (watched) tab.

Unlike diary entries, the Films tab includes titles marked as watched or rated
without a dated diary log. Intended for a daily GitHub Actions workflow.
"""
import csv
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from curl_cffi import requests

ROOT = "https://letterboxd.com/"
USERNAME = os.environ.get("LETTERBOXD_USERNAME", "kennypickettfan")
OUTPUT = Path("images/letterboxd-watched.csv")
MAX_PAGES = 25
HEADERS = {
    "referer": ROOT,
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "cache-control": "no-cache",
}
session = requests.Session()


def get_page(url):
    for attempt in range(1, 4):
        last = None
        for profile in ("safari17_0", "chrome"):
            try:
                response = session.get(
                    url, headers=HEADERS, timeout=(15, 45), impersonate=profile
                )
                last = response
                if response.status_code == 200 and "cf_chl_" not in response.text:
                    return response.text
            except Exception as exc:
                print(f"Fetch error ({profile}): {exc}", file=sys.stderr)
        print(f"Fetch attempt {attempt} failed for {url} (status: "
              f"{getattr(last, 'status_code', 'unknown')})", file=sys.stderr)
        time.sleep(min(4 * attempt, 12))
    raise RuntimeError(f"Unable to access Letterboxd Films page: {url}")


def extract_posters(html):
    soup = BeautifulSoup(html, "html.parser")
    # Current and legacy Letterboxd poster layouts.
    containers = soup.select(
        "li.poster-container, li.posteritem, li.griditem, "
        ".poster-grid > li, .poster-list > li, li[data-film-id]"
    )
    if not containers:
        containers = list(dict.fromkeys(
            child.find_parent("li") or child
            for child in soup.select("[data-item-slug], [data-film-slug]")
        ))
    result = []
    for outer in containers:
        inner = outer if outer.has_attr("data-item-slug") else (
            outer.select_one("[data-item-slug], [data-film-slug], [data-target-link]")
            or outer
        )
        attrs = {**outer.attrs, **inner.attrs}
        slug = attrs.get("data-item-slug") or attrs.get("data-film-slug")
        href = attrs.get("data-target-link") or ""
        if not slug and href:
            m = re.search(r"/film/([^/?#]+)/?", href)
            if m:
                slug = m.group(1)
        if not slug:
            film_link = outer.select_one('a[href^="/film/"]')
            if film_link:
                m = re.search(r"/film/([^/?#]+)/?", film_link.get("href", ""))
                slug = m.group(1) if m else ""
        if not slug:
            continue

        raw_name = attrs.get("data-item-name") or attrs.get("data-film-name") or ""
        if not raw_name:
            img = outer.select_one("img[alt]")
            if img:
                raw_name = img.get("alt", "")
        raw_name = str(raw_name)
        m = re.match(r"^(.*?)\s*\((\d{4})\)\s*$", raw_name)
        if m:
            title, year = m.group(1).strip(), m.group(2)
        else:
            title = re.sub(r"\s*\(\d{4}\)$", "", raw_name).strip()
            year = ""
        rating = attrs.get("data-owner-rating") or ""
        if isinstance(rating, list):
            rating = " ".join(rating)
        result.append({
            "title": title, "year": year, "slug": slug,
            "rating": str(rating), "film_url": urljoin(ROOT, f"film/{slug}/"),
        })

    next_link = soup.select_one("a.next, a.paginate-next")
    next_page = bool(next_link and next_link.get("href"))
    markers = {
        "containers": len(containers),
        "data_item_slug": len(soup.select("[data-item-slug]")),
        "data_target_link": len(soup.select("[data-target-link]")),
        "data_film_id": len(soup.select("[data-film-id]")),
    }
    if not result:
        snippet = str(soup.select_one(".poster-grid, .poster-list") or soup.body or "")[:1500]
        print(f"DEBUG: {markers}; page markup preview: {snippet}", file=sys.stderr)
    return result, next_page, markers


def main():
    all_films = {}
    for page in range(1, MAX_PAGES + 1):
        url = urljoin(ROOT, f"{USERNAME}/films/" + (f"page/{page}/" if page > 1 else ""))
        entries, next_page, markers = extract_posters(get_page(url))
        print(f"Watched page {page}: {len(entries)} films; {markers}")
        if not entries:
            raise RuntimeError("No watched-film posters found (possible site/layout change)")
        previous = len(all_films)
        for entry in entries:
            all_films.setdefault(entry["slug"], entry)
        if len(all_films) == previous:
            raise RuntimeError("Repeated watched page; stopping rather than silently truncating")
        if not next_page:
            break
        time.sleep(0.6)
    else:
        raise RuntimeError("Reached MAX_PAGES without the final page")

    films = sorted(all_films.values(), key=lambda f: f["title"].lower())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["title", "year", "slug", "rating", "film_url"])
        writer.writeheader()
        writer.writerows(films)

    print(f"Exported {len(films)} watched films to {OUTPUT}")
    for name in ("No Country for Old Men", "12 Angry Men", "Apocalypse Now"):
        matches = [f for f in films if f["title"].casefold() == name.casefold()]
        print(f"CHECK: {name}: {matches or 'not in scraped Films list'}")
    if len(films) < 234:
        raise RuntimeError("Watched list unexpectedly shorter than the existing diary")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
