#!/usr/bin/env python3
"""
scraper.py
==========

A generic, production-quality web scraper CLI tool.

Downloads HTML with `requests`, parses it with BeautifulSoup, extracts
structured records, follows pagination, and saves the results to CSV or
JSON. The extraction logic targets https://books.toscrape.com/ by default
(a website built specifically for scraping practice) but is written so the
CSS-selector logic in `extract_data()` and `find_next_page()` can be swapped
out for any other site with a similar list/pagination layout.

Usage:
    python scraper.py --url "https://books.toscrape.com/" --pages 5 --format csv

Run `python scraper.py --help` for the full list of options.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import time
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 ScraperBot/1.0"
)
DEFAULT_TIMEOUT = 10        # seconds, per request
MAX_RETRIES = 3             # retry attempts for transient failures
RETRY_BACKOFF_BASE = 2      # seconds; multiplied by attempt number

LOG_DIR = Path("logs")
OUTPUT_DIR = Path("output")
LOG_FILE = LOG_DIR / "scraper.log"

# Maps the CSS rating classes used by books.toscrape.com to numeric values.
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}


# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #
def configure_logging(verbose: bool) -> logging.Logger:
    """
    Configure logging to both a rotating-friendly log file and the terminal.

    Args:
        verbose: If True, the console handler is set to DEBUG; otherwise INFO.
                 The file handler always logs at DEBUG level.

    Returns:
        A configured `logging.Logger` instance named "scraper".
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("scraper")
    logger.setLevel(logging.DEBUG)
    logger.handlers.clear()  # prevent duplicate handlers if called more than once

    file_formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter = logging.Formatter("%(levelname)-8s | %(message)s")

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)

    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    console_handler.setFormatter(console_formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return logger


# --------------------------------------------------------------------------- #
# Argument parsing
# --------------------------------------------------------------------------- #
def parse_arguments() -> argparse.Namespace:
    """Define and parse command-line arguments for the scraper."""
    parser = argparse.ArgumentParser(
        prog="scraper.py",
        description=(
            "Generic web scraper: downloads, parses, extracts, and saves "
            "structured data from a paginated website."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Starting webpage URL to scrape (must include http:// or https://).",
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=5,
        help="Maximum number of pages to scrape.",
    )
    parser.add_argument(
        "--output",
        default="data",
        help="Output filename, without extension (extension is added automatically).",
    )
    parser.add_argument(
        "--format",
        choices=["csv", "json"],
        default="csv",
        help="Output file format.",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between page requests (be polite to servers).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable detailed (DEBUG-level) console logging.",
    )
    return parser.parse_args()


# --------------------------------------------------------------------------- #
# Networking
# --------------------------------------------------------------------------- #
def download_page(
    url: str,
    logger: logging.Logger,
    timeout: int = DEFAULT_TIMEOUT,
) -> Optional[str]:
    """
    Download HTML content from a URL with retries and robust error handling.

    Retries on timeouts, connection errors, and 5xx server errors using a
    linear backoff. Does not retry on 404/403, since those are unlikely to
    resolve on their own.

    Args:
        url: The URL to download.
        logger: Logger instance for status/error reporting.
        timeout: Per-request timeout in seconds.

    Returns:
        The page's HTML text on success, or None if the download ultimately
        failed. This function never raises; all failures are caught and logged.
    """
    headers = {"User-Agent": DEFAULT_USER_AGENT}

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            logger.debug(f"Requesting {url} (attempt {attempt}/{MAX_RETRIES})")
            response = requests.get(url, headers=headers, timeout=timeout)

            if response.status_code == 200:
                return response.text

            if response.status_code == 404:
                logger.error(f"404 Not Found: {url}")
                return None

            if response.status_code == 403:
                logger.error(f"403 Forbidden: {url}")
                return None

            if response.status_code >= 500:
                logger.warning(
                    f"Server error {response.status_code} on {url}; "
                    f"will retry ({attempt}/{MAX_RETRIES})"
                )
            else:
                logger.warning(
                    f"Unexpected status {response.status_code} on {url}; "
                    f"will retry ({attempt}/{MAX_RETRIES})"
                )

        except requests.exceptions.Timeout:
            logger.warning(f"Timeout requesting {url} (attempt {attempt}/{MAX_RETRIES})")
        except requests.exceptions.ConnectionError:
            logger.warning(f"Connection error requesting {url} (attempt {attempt}/{MAX_RETRIES})")
        except requests.exceptions.RequestException as exc:
            # Covers malformed URLs (InvalidURL/MissingSchema) and any other
            # request-level failure that is not worth retrying.
            logger.error(f"Request failed for {url}: {exc}")
            return None

        if attempt < MAX_RETRIES:
            time.sleep(RETRY_BACKOFF_BASE * attempt)

    logger.error(f"Failed to download {url} after {MAX_RETRIES} attempts")
    return None


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #
def parse_html(html: str, logger: logging.Logger) -> Optional[BeautifulSoup]:
    """
    Parse raw HTML text into a BeautifulSoup object.

    Args:
        html: Raw HTML content.
        logger: Logger instance.

    Returns:
        A BeautifulSoup object, or None if parsing failed (e.g. severely
        malformed input that the parser cannot handle at all).
    """
    try:
        return BeautifulSoup(html, "html.parser")
    except Exception as exc:  # BeautifulSoup is generally resilient, but guard anyway
        logger.error(f"Failed to parse HTML: {exc}")
        return None


# --------------------------------------------------------------------------- #
# Extraction
# --------------------------------------------------------------------------- #
def extract_data(soup: BeautifulSoup, base_url: str, logger: logging.Logger) -> list[dict]:
    """
    Extract structured book records from a parsed catalogue page.

    This targets the markup of https://books.toscrape.com/, where each book
    is an <article class="product_pod"> element. The function is written
    defensively: any missing field is stored as None rather than raising an
    exception, and a single malformed record is skipped without aborting
    the whole page.

    To adapt this scraper to a different website, change the selectors in
    this function (and in `find_next_page`) to match that site's markup —
    the rest of the pipeline (downloading, retrying, saving, logging) stays
    the same.

    Args:
        soup: Parsed HTML of the page.
        base_url: The page's URL, used to resolve relative links to absolute ones.
        logger: Logger instance.

    Returns:
        A list of dictionaries, each representing one extracted record, with
        keys: title, price, availability, rating, link.
    """
    records: list[dict] = []
    articles = soup.find_all("article", class_="product_pod")

    if not articles:
        logger.warning("No product items found on this page.")
        return records

    for article in articles:
        try:
            # --- Title & link (both come from the <h3><a> tag) ---
            title = None
            link = None
            title_tag = article.find("h3")
            if title_tag is not None:
                anchor = title_tag.find("a")
                if anchor is not None:
                    title = anchor.get("title") or anchor.text.strip() or None
                    href = anchor.get("href")
                    if href:
                        link = urljoin(base_url, href)

            # --- Price ---
            price_tag = article.find("p", class_="price_color")
            price = price_tag.text.strip() if price_tag else None

            # --- Availability ---
            availability_tag = article.find("p", class_="instock availability")
            availability = availability_tag.text.strip() if availability_tag else None

            # --- Rating (encoded as a CSS class like "star-rating Three") ---
            rating = None
            rating_tag = article.find("p", class_="star-rating")
            if rating_tag is not None:
                for css_class in rating_tag.get("class", []):
                    if css_class in RATING_WORDS:
                        rating = RATING_WORDS[css_class]
                        break

            records.append(
                {
                    "title": title,
                    "price": price,
                    "availability": availability,
                    "rating": rating,
                    "link": link,
                }
            )

        except Exception as exc:
            logger.warning(f"Skipping a malformed record on {base_url}: {exc}")
            continue

    return records


def find_next_page(
    soup: BeautifulSoup,
    current_url: str,
    logger: logging.Logger,
) -> Optional[str]:
    """
    Locate the absolute URL of the next page in the pagination sequence.

    Args:
        soup: Parsed HTML of the current page.
        current_url: URL of the current page, used to resolve relative links.
        logger: Logger instance.

    Returns:
        The absolute URL of the next page, or None if there is no next page
        (i.e. this is the last page) or the pagination markup could not be
        found/understood.
    """
    try:
        next_li = soup.find("li", class_="next")
        if next_li is not None:
            anchor = next_li.find("a")
            if anchor is not None and anchor.get("href"):
                return urljoin(current_url, anchor["href"])
    except Exception as exc:
        logger.warning(f"Error while locating next page from {current_url}: {exc}")
    return None


# --------------------------------------------------------------------------- #
# Saving
# --------------------------------------------------------------------------- #
def save_csv(records: list[dict], output_path: Path, logger: logging.Logger) -> bool:
    """
    Save a list of record dictionaries to a CSV file.

    Args:
        records: List of dictionaries with uniform keys.
        output_path: Destination file path.
        logger: Logger instance.

    Returns:
        True if the file was written successfully, False otherwise.
    """
    if not records:
        logger.warning("No records to save; skipping CSV write.")
        return False
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(records[0].keys())
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(records)
        logger.info(f"Saved {len(records)} records to {output_path} (CSV)")
        return True
    except OSError as exc:
        logger.error(f"Failed to write CSV file {output_path}: {exc}")
        return False


def save_json(records: list[dict], output_path: Path, logger: logging.Logger) -> bool:
    """
    Save a list of record dictionaries to a JSON file.

    Args:
        records: List of dictionaries to serialize.
        output_path: Destination file path.
        logger: Logger instance.

    Returns:
        True if the file was written successfully, False otherwise.
    """
    if not records:
        logger.warning("No records to save; skipping JSON write.")
        return False
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2, ensure_ascii=False)
        logger.info(f"Saved {len(records)} records to {output_path} (JSON)")
        return True
    except OSError as exc:
        logger.error(f"Failed to write JSON file {output_path}: {exc}")
        return False


# --------------------------------------------------------------------------- #
# Main orchestration
# --------------------------------------------------------------------------- #
def main() -> None:
    """Entry point: parse arguments, run the scrape loop, save output, report summary."""
    args = parse_arguments()
    logger = configure_logging(args.verbose)

    start_time = time.time()
    all_records: list[dict] = []
    pages_visited = 0
    error_count = 0

    # --- Validate the starting URL before doing any network I/O ---
    parsed = urlparse(args.url)
    if not parsed.scheme or not parsed.netloc:
        logger.error(f"Invalid URL provided: {args.url}")
        print(
            f"Error: '{args.url}' is not a valid URL. "
            f"Include the scheme, e.g. https://example.com"
        )
        return

    current_url: Optional[str] = args.url
    logger.info(f"Starting scrape of {current_url} (max {args.pages} page(s))")

    while current_url and pages_visited < args.pages:
        logger.info(f"Fetching page {pages_visited + 1}: {current_url}")
        html = download_page(current_url, logger)

        if html is None:
            error_count += 1
            logger.error(f"Stopping pagination: failed to download {current_url}")
            print(f"  Page {pages_visited + 1}: request failed, stopping.")
            break

        soup = parse_html(html, logger)
        if soup is None:
            error_count += 1
            print(f"  Page {pages_visited + 1}: failed to parse HTML, stopping.")
            break

        page_records = extract_data(soup, current_url, logger)
        all_records.extend(page_records)
        pages_visited += 1
        logger.info(f"Page {pages_visited}: extracted {len(page_records)} record(s)")
        print(f"  Page {pages_visited}: extracted {len(page_records)} record(s)")

        if pages_visited >= args.pages:
            logger.info("Reached the maximum page limit.")
            break

        next_url = find_next_page(soup, current_url, logger)
        if not next_url:
            logger.info("No further pages found; stopping pagination.")
            break

        current_url = next_url
        time.sleep(args.delay)

    # --- Save results ---
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{args.output}.{args.format}"

    if args.format == "csv":
        saved = save_csv(all_records, output_path, logger)
    else:
        saved = save_json(all_records, output_path, logger)

    if not saved:
        error_count += 1

    elapsed = time.time() - start_time

    # --- Summary report ---
    print("\n" + "=" * 45)
    print("SCRAPING SUMMARY")
    print("=" * 45)
    print(f"Pages visited:       {pages_visited}")
    print(f"Records extracted:   {len(all_records)}")
    print(f"Output file:         {output_path if saved else 'N/A (save failed)'}")
    print(f"Execution time:      {elapsed:.2f} seconds")
    print(f"Errors encountered:  {error_count}")
    print("=" * 45)

    logger.info(
        f"Scraping complete. pages={pages_visited} records={len(all_records)} "
        f"errors={error_count} time={elapsed:.2f}s"
    )


if __name__ == "__main__":
    main()
