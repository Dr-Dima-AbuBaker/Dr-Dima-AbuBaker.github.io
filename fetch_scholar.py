"""
Google Scholar → data.json Updater
===================================
Fetches your publications from Google Scholar and updates data.json.
Merges with existing manual entries — never deletes your custom data.

Publication data comes from Google Scholar via SerpApi rather than by
scraping scholar.google.com directly. Google blocks datacenter IP ranges,
so a direct scrape works from a home connection but reliably fails from
CI runners; SerpApi queries Scholar from IPs Google serves and returns the
same citation counts.

Requirements:
    pip install requests
    export SERPAPI_KEY=...        # free tier: https://serpapi.com

Usage:
    python fetch_scholar.py                          # uses scholarId from data.json
    python fetch_scholar.py --scholar-id "ABC123"    # specify directly
    python fetch_scholar.py --dry-run                # show changes, write nothing

What it does:
    1. Reads your current data.json
    2. Fetches publications from Google Scholar
    3. For EXISTING papers: updates citation count only
    4. For NEW papers: adds them with Scholar data (you fill in image/thumbnail later)
    5. Saves updated data.json (backs up original as data.backup.json)
"""

import json
import sys
import os
import shutil
import argparse
from datetime import datetime

try:
    import requests
except ImportError:
    print("Install requests first:")
    print("  pip install requests")
    sys.exit(1)


DATA_FILE = "data.json"
BACKUP_FILE = "data.backup.json"
PLACEHOLDER_IMAGE = "images/publications/placeholder.svg"
PLACEHOLDER_THUMB = "images/publications/placeholder-thumb.svg"

SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
REQUEST_TIMEOUT = 60
PAGE_SIZE = 100


def load_data():
    """Load existing data.json."""
    if not os.path.exists(DATA_FILE):
        print(f"Error: {DATA_FILE} not found.")
        sys.exit(1)
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    """Backup and save data.json."""
    if os.path.exists(DATA_FILE):
        shutil.copy2(DATA_FILE, BACKUP_FILE)
        print(f"  Backed up to {BACKUP_FILE}")
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved {DATA_FILE}")


def normalize_title(title):
    """Normalize title for matching."""
    return title.lower().strip().rstrip(".")


def guess_type(venue):
    """Guess publication type from venue name."""
    v = venue.lower()
    if any(k in v for k in ["journal", "transactions", "letters", "review"]):
        return "journal"
    if any(k in v for k in ["workshop", "w/"]):
        return "workshop"
    return "conference"


def format_bibtex(pub):
    """Generate a simple BibTeX entry from a normalized publication dict."""
    authors = pub.get("authors") or "Unknown"
    title = pub.get("title") or "Untitled"
    year = pub.get("year") or "????"
    venue = pub.get("venue") or ""

    key = authors.split(" ")[0].lower() + str(year)
    bib_type = "article" if "journal" in venue.lower() else "inproceedings"

    return f"@{bib_type}{{{key},title={{{title}}},author={{{authors}}},year={{{year}}}}}"


def get_api_key():
    """Read the SerpApi key from the environment."""
    key = os.environ.get("SERPAPI_KEY", "").strip()
    if not key:
        print("Error: SERPAPI_KEY is not set.")
        print("  1. Get a free key at https://serpapi.com (250 searches/month)")
        print("  2. Locally:  export SERPAPI_KEY=your_key")
        print("     In CI:    add it as the repository secret SERPAPI_KEY")
        sys.exit(1)
    return key


def serpapi_get(api_key, **params):
    """Call SerpApi and return the parsed JSON, exiting on any error."""
    params["api_key"] = api_key
    try:
        response = requests.get(SERPAPI_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as e:
        print(f"Error: could not reach SerpApi: {e}")
        sys.exit(1)

    try:
        payload = response.json()
    except ValueError:
        print(f"Error: SerpApi returned a non-JSON response (HTTP {response.status_code}).")
        sys.exit(1)

    # SerpApi reports failures in an `error` key, on both 2xx and 4xx responses.
    if payload.get("error"):
        print(f"Error from SerpApi (HTTP {response.status_code}): {payload['error']}")
        if response.status_code == 401:
            print("  The SERPAPI_KEY looks invalid. Check https://serpapi.com/manage-api-key")
        elif response.status_code == 429:
            print("  Free tier is 250 searches/month and 50 requests/hour.")
        sys.exit(1)

    if response.status_code >= 400:
        print(f"Error: SerpApi returned HTTP {response.status_code}.")
        sys.exit(1)

    return payload


def parse_year(value):
    """Scholar returns the year as a string, and omits it for some entries."""
    text = str(value or "").strip()
    return int(text) if text.isdigit() else 0


def parse_citations(article):
    """Read a citation count off an author-API article.

    Scholar omits `cited_by` entirely for never-cited papers, so a missing
    key means zero rather than an unparsed response.
    """
    cited_by = article.get("cited_by") or {}
    value = cited_by.get("value")
    return int(value) if isinstance(value, int) else 0


def fetch_author_articles(api_key, scholar_id):
    """Fetch every article on the author's Scholar profile, following pagination."""
    articles = []
    params = {
        "engine": "google_scholar_author",
        "author_id": scholar_id,
        "hl": "en",
        "num": PAGE_SIZE,
        "start": 0,
    }

    while True:
        payload = serpapi_get(api_key, **params)
        page = payload.get("articles") or []
        articles.extend(page)

        # Absence of `serpapi_pagination.next` is the only end-of-results signal.
        if not (payload.get("serpapi_pagination") or {}).get("next"):
            break
        if not page:
            break
        params["start"] += PAGE_SIZE

    return articles


def fetch_citation_details(api_key, citation_id):
    """Fetch the detail record for one article (abstract, journal, real link).

    The author API only returns a squashed `publication` string like
    "Genome biology 9 (9), 1-9, 2008", so new papers get one extra lookup to
    pick up a clean journal name and abstract. Existing papers never need it.
    """
    payload = serpapi_get(
        api_key,
        engine="google_scholar_author",
        view_op="view_citation",
        citation_id=citation_id,
        hl="en",
    )
    return payload.get("citation") or {}


def article_to_publication(article, details=None):
    """Normalize a SerpApi article (plus optional detail record) for merging."""
    details = details or {}

    title = details.get("title") or article.get("title") or "Untitled"
    authors = details.get("authors") or article.get("authors") or "Unknown"
    venue = details.get("journal") or article.get("publication") or ""
    abstract = details.get("description") or ""

    year = parse_year(article.get("year"))
    if not year:
        # Detail records carry dates like "2006/11".
        year = parse_year(str(details.get("publication_date", "")).split("/")[0])

    # `link` on an author-API article points back at Scholar; the detail
    # record's `link` is the publisher's page, which is what we want on the site.
    pub_url = details.get("link") or article.get("link") or "#"

    pub = {
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "citations": parse_citations(article),
        "description": abstract[:200] + ("..." if len(abstract) > 200 else ""),
        "type": guess_type(venue),
        "pub_url": pub_url,
    }
    pub["bibtex"] = format_bibtex(pub)
    return pub


def fetch_scholar_publications(scholar_id, known_titles):
    """Fetch publications from Google Scholar via SerpApi.

    `known_titles` are the normalized titles already in data.json; anything
    matching one of those skips the per-article detail lookup, since the merge
    only refreshes its citation count.
    """
    print(f"\nFetching publications for Scholar ID: {scholar_id}")

    api_key = get_api_key()
    articles = fetch_author_articles(api_key, scholar_id)
    total = len(articles)
    print(f"  Found {total} publications on the profile.\n")

    publications = []
    for i, article in enumerate(articles, 1):
        title = article.get("title", "Untitled")
        details = None

        if normalize_title(title) not in known_titles and article.get("citation_id"):
            print(f"  [{i}/{total}] {title[:60]}... (new — fetching details)")
            details = fetch_citation_details(api_key, article["citation_id"])
        else:
            print(f"  [{i}/{total}] {title[:60]}... ({parse_citations(article)} citations)")

        publications.append(article_to_publication(article, details))

    return publications


def merge_publications(existing, fetched, highlight_author):
    """Merge fetched publications into existing list."""
    # Index existing by normalized title
    existing_map = {}
    for pub in existing:
        key = normalize_title(pub["title"])
        existing_map[key] = pub

    updated_count = 0
    added_count = 0

    for fp in fetched:
        key = normalize_title(fp["title"])

        if key in existing_map:
            # UPDATE: only update citation count (and URLs if they were placeholders)
            old_count = existing_map[key].get("citations", 0)
            new_count = fp["citations"]

            # A previously-cited paper reading as 0 means the count went
            # missing from the response, not that Scholar forgot the citations.
            if new_count == 0 and old_count > 0:
                print(f"  Kept citations (no count returned): {fp['title'][:50]}... ({old_count})")
            elif new_count != old_count:
                existing_map[key]["citations"] = new_count
                print(f"  Updated citations: {fp['title'][:50]}... ({old_count} → {new_count})")
                updated_count += 1

            if existing_map[key].get("url", "#") == "#" and fp["pub_url"] != "#":
                existing_map[key]["url"] = fp["pub_url"]
            if existing_map[key].get("pdfUrl", "#") == "#" and fp["pub_url"] != "#":
                existing_map[key]["pdfUrl"] = fp["pub_url"]
        else:
            # NEW: add with placeholder images
            new_pub = {
                "title": fp["title"],
                "authors": fp["authors"],
                "highlightAuthor": highlight_author,
                "venue": fp["venue"],
                "year": fp["year"],
                "type": fp["type"],
                "image": PLACEHOLDER_IMAGE,
                "thumbnail": PLACEHOLDER_THUMB,
                "description": fp["description"],
                "pdfUrl": fp.get("pub_url", "#"),
                "url": fp.get("pub_url", "#"),
                "citations": fp["citations"],
                "bibtex": fp["bibtex"],
            }
            existing.append(new_pub)
            print(f"  Added new: {fp['title'][:60]}...")
            added_count += 1

    print(f"\n  Summary: {updated_count} updated, {added_count} new, {len(existing)} total")
    return existing


def main():
    parser = argparse.ArgumentParser(description="Update data.json from Google Scholar")
    parser.add_argument("--scholar-id", help="Google Scholar author ID (e.g., 'dkNRBCEAAAAJ')")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would change without writing data.json")
    args = parser.parse_args()

    # Load data
    data = load_data()

    # Get Scholar ID
    scholar_id = args.scholar_id
    if not scholar_id:
        scholar_id = data.get("settings", {}).get("scholarId", "")
    if not scholar_id:
        print("No Scholar ID provided.")
        print("Options:")
        print('  1. Add "scholarId" to settings in data.json')
        print("  2. Run: python fetch_scholar.py --scholar-id YOUR_ID")
        print("\nYour Scholar ID is in your Google Scholar profile URL:")
        print("  https://scholar.google.com/citations?user=YOUR_ID")
        sys.exit(1)

    # Save Scholar ID to settings
    if "settings" not in data:
        data["settings"] = {}
    data["settings"]["scholarId"] = scholar_id

    # Fetch
    known_titles = {normalize_title(p["title"]) for p in data.get("publications", [])}
    fetched = fetch_scholar_publications(scholar_id, known_titles)

    # Get highlight author name
    highlight = data["publications"][0]["highlightAuthor"] if data.get("publications") else ""
    if not highlight:
        highlight = data.get("profile", {}).get("name", "")

    # Merge
    print("\nMerging with existing publications...")
    data["publications"] = merge_publications(data["publications"], fetched, highlight)

    # Sort by year
    data["publications"].sort(key=lambda p: p.get("year", 0), reverse=True)

    if args.dry_run:
        print("\nDry run — data.json was not modified.")
        return

    # Save
    print("\nSaving...")
    save_data(data)

    print(f"\nDone! Updated at {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("\nNext steps:")
    print("  - Review data.json for any new entries")
    print("  - Replace placeholder images for new papers")
    print("  - Add PDF URLs for new papers")
    print("  - Push to GitHub: git add data.json && git commit -m 'Update publications' && git push")


if __name__ == "__main__":
    main()
