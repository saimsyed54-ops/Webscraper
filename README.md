# Web Scraper CLI

A generic, production-quality Python command-line tool for scraping
structured data from paginated websites. Built with **requests** and
**BeautifulSoup**, it downloads pages, extracts records, follows pagination
automatically, and saves results to CSV or JSON — with robust error
handling and logging throughout.

Demonstrated against [books.toscrape.com](https://books.toscrape.com/),
a site built specifically for scraping practice.

---

## Installation

Requires Python 3.8+.

**Check Python is installed (Windows / PowerShell):**
```powershell
py --version
```

**Install dependencies:**
```powershell
py -m pip install requests beautifulsoup4
```

Or, if `requirements.txt` is present in the folder:
```powershell
py -m pip install -r requirements.txt
```

---

## How to Run

Open the project folder in a terminal and run:

```powershell
py scraper.py --url "https://books.toscrape.com/" --pages 5 --format csv
```

This scrapes up to 5 pages and writes results to `output/data.csv`.
The `logs/` and `output/` folders are created automatically on first run.

---

## Command-Line Arguments

| Argument    | Required | Default | Description |
|-------------|----------|---------|--------------|
| `--url`     | Yes      | —       | Starting webpage URL to scrape. Must include `http://` or `https://`. |
| `--pages`   | No       | `5`     | Maximum number of pages to scrape. |
| `--output`  | No       | `data`  | Output filename, without extension. |
| `--format`  | No       | `csv`   | Output format: `csv` or `json`. |
| `--delay`   | No       | `1.0`   | Delay in seconds between page requests. |
| `--verbose` | No       | off     | Enable detailed (DEBUG-level) console logging. |

See all options anytime with:
```powershell
py scraper.py --help
```

---

## Example Commands

Scrape the first 3 pages and save as JSON:
```powershell
py scraper.py --url "https://books.toscrape.com/" --pages 3 --format json
```

Scrape with a longer delay and verbose logging:
```powershell
py scraper.py --url "https://books.toscrape.com/" --pages 10 --delay 2 --verbose
```

---

## Example Output

**Terminal:**
