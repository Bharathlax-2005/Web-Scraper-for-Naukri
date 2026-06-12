"""
NAUKRI JOB SCRAPER
==================
Reads keywords from output/keywords_*.json (produced by keyword_discovery.py)
and scrapes job listings for every keyword in parallel.

Output files saved to output/:
    naukri_jobs_TIMESTAMP.csv
    naukri_jobs_TIMESTAMP.xlsx

Usage:
    python naukri_scraper.py                         # uses latest keywords file
    python naukri_scraper.py output/keywords_XYZ.json  # use a specific file

Requirements:
    pip install undetected-chromedriver selenium beautifulsoup4 lxml rich pandas openpyxl
"""

import sys, re, csv, json, time, logging, threading, traceback
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.panel import Panel
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By

console = Console()

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════
BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR   = BASE_DIR / "logs"
OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

TIMESTAMP  = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_FILE   = OUTPUT_DIR / f"naukri_jobs_{TIMESTAMP}.csv"
EXCEL_FILE = OUTPUT_DIR / f"naukri_jobs_{TIMESTAMP}.xlsx"
FAILED_LOG = LOGS_DIR   / f"failed_urls_{TIMESTAMP}.txt"

MAX_PAGES_PER_KEYWORD = 5    # 5 pages x 20 jobs = up to 100 jobs/keyword
MAX_WORKERS           = 2    # parallel Chrome browser instances
PAGE_WAIT             = 3.5  # seconds to wait after page load

logging.basicConfig(
    filename=LOGS_DIR / f"scraper_{TIMESTAMP}.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ═══════════════════════════════════════════════════════════════
#  DATA MODEL
# ═══════════════════════════════════════════════════════════════
@dataclass
class JobRecord:
    job_title:       str = "NULL"
    company_name:    str = "NULL"
    location:        str = "NULL"
    experience:      str = "NULL"
    salary:          str = "NULL"
    employment_type: str = "NULL"
    skills:          str = "NULL"
    job_description: str = "NULL"
    posted_date:     str = "NULL"
    job_url:         str = "NULL"
    scraped_at:      str = field(default_factory=lambda: datetime.now().isoformat())
    keyword_source:  str = "NULL"

CSV_FIELDS = list(JobRecord.__dataclass_fields__.keys())

# ═══════════════════════════════════════════════════════════════
#  THREAD-SAFE UTILITIES
# ═══════════════════════════════════════════════════════════════
class Stats:
    def __init__(self):
        self._lock       = threading.Lock()
        self.jobs_discovered = 0
        self.jobs_scraped    = 0
        self.jobs_skipped    = 0
        self.jobs_failed     = 0

    def bump(self, attr: str, n: int = 1):
        with self._lock:
            setattr(self, attr, getattr(self, attr) + n)

stats      = Stats()
seen_urls: set = set()
seen_lock  = threading.Lock()
write_lock = threading.Lock()


def is_new_url(url: str) -> bool:
    with seen_lock:
        if url in seen_urls:
            return False
        seen_urls.add(url)
        return True


def init_csv():
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        csv.DictWriter(f, fieldnames=CSV_FIELDS).writeheader()


def append_csv(record: JobRecord):
    with write_lock:
        with open(CSV_FILE, "a", newline="", encoding="utf-8-sig") as f:
            csv.DictWriter(f, fieldnames=CSV_FIELDS).writerow(asdict(record))


def save_excel():
    try:
        import pandas as pd
        pd.read_csv(CSV_FILE, encoding="utf-8-sig").to_excel(
            EXCEL_FILE, index=False, engine="openpyxl"
        )
        console.print(f"[bold green]Excel saved -> {EXCEL_FILE}[/bold green]")
    except Exception as e:
        console.print(f"[yellow]Excel export skipped: {e}[/yellow]")

# ═══════════════════════════════════════════════════════════════
#  CHROME DRIVER HELPERS
# ═══════════════════════════════════════════════════════════════
def make_driver() -> uc.Chrome:
    """Minimal UC setup — the only config that bypasses Naukri's WAF."""
    opts = uc.ChromeOptions()
    opts.add_argument("--disable-notifications")
    opts.add_argument("--mute-audio")
    opts.add_argument("--lang=en-US")
    driver = uc.Chrome(options=opts)
    driver.implicitly_wait(5)
    return driver


def quit_driver(driver):
    """Silently close driver — suppresses harmless WinError 6 noise."""
    for fn in (driver.service.stop, driver.quit):
        try:
            fn()
        except Exception:
            pass


def safe_get(driver, url: str, wait: float = PAGE_WAIT) -> bool:
    try:
        driver.get(url)
        time.sleep(wait)
        return True
    except Exception as e:
        logging.warning(f"Navigation error [{url}]: {e}")
        return False


def page_soup(driver) -> BeautifulSoup:
    return BeautifulSoup(driver.page_source, "lxml")

# ═══════════════════════════════════════════════════════════════
#  KEYWORDS LOADER
# ═══════════════════════════════════════════════════════════════
def load_keywords(keywords_file: Optional[Path] = None) -> list[str]:
    """
    Load keywords from a JSON file.
    If no file is given, auto-picks the most recent keywords_*.json in output/.
    """
    if keywords_file and keywords_file.exists():
        target = keywords_file
    else:
        files = sorted(OUTPUT_DIR.glob("keywords_*.json"), reverse=True)
        if not files:
            return []
        target = files[0]

    with open(target, encoding="utf-8") as f:
        keywords = json.load(f)

    console.print(f"[bold green]Loaded {len(keywords)} keywords from:[/bold green] {target}\n")
    return keywords

# ═══════════════════════════════════════════════════════════════
#  JOB SEARCH & EXTRACTION
# ═══════════════════════════════════════════════════════════════
def _slug(keyword: str) -> str:
    return re.sub(r"\s+", "-", re.sub(r"[^a-zA-Z0-9\s-]", "", keyword).strip()).lower()


def get_job_urls(driver, keyword: str, page: int) -> list[str]:
    slug = _slug(keyword)
    url = (f"https://www.naukri.com/{slug}-jobs"
           if page == 1 else
           f"https://www.naukri.com/{slug}-jobs-{page}")

    if not safe_get(driver, url):
        return []

    pg = page_soup(driver)
    title = pg.title.string if pg.title else ""
    if "access denied" in title.lower() or "404" in title:
        return []

    urls = []
    for a in pg.find_all("a", href=True):
        href = a["href"]
        if "job-listings" in href:
            if not href.startswith("http"):
                href = "https://www.naukri.com" + href
            urls.append(href)

    return list(dict.fromkeys(urls))  # deduplicated, order preserved


def extract_job(driver, job_url: str, keyword: str) -> Optional[JobRecord]:
    if not safe_get(driver, job_url, wait=2.5):
        return None

    pg = page_soup(driver)
    page_title = pg.title.string if pg.title else ""
    if "access denied" in page_title.lower():
        return None

    def txt(*selectors, default="NULL") -> str:
        for sel in selectors:
            el = pg.select_one(sel)
            if el:
                t = el.get_text(separator=" ", strip=True)
                if t:
                    return t
        return default

    # Job title
    job_title = txt("h1[class*='jd-header-title']", "h1[class*='title']", "h1")

    # Company name — strip embedded rating numbers
    comp_el = pg.select_one(
        "div[class*='jd-header-comp-name'], a[class*='comp-name'], [class*='companyName']"
    )
    if comp_el:
        company = next(
            (t.strip() for t in comp_el.strings
             if t.strip()
             and not re.match(r'^\d+[\.\d]*[KM]?\s*Reviews?$', t.strip(), re.I)
             and not re.match(r'^\d+\.\d+$', t.strip())),
            comp_el.get_text(strip=True)
        )
        company = re.sub(r"\s*\d+\.\d+.*$", "", company).strip() or "NULL"
    else:
        company = "NULL"

    # Location
    loc_el = pg.select_one("span[class*='jhc__location'], div[class*='jhc__loc']")
    location = loc_el.get_text(strip=True) if loc_el else "NULL"

    # Experience
    exp_el = pg.select_one("div[class*='jhc__exp'], div[class*='exp-salary'] div:first-child")
    experience = (exp_el.get_text(strip=True) if exp_el
                  else txt("[class*='exp'] span", ".exp-wrap span"))

    # Salary
    sal_el = pg.select_one("div[class*='jhc__salary']")
    salary = (sal_el.get_text(strip=True) if sal_el
              else txt("[class*='salary'] span", "[class*='ctc'] span"))

    # Employment type
    emp_type = txt("[class*='job-type']", "[class*='jobType']", "[class*='employment-type']")

    # Skills
    skill_els = pg.select(
        ".key-skill span, [class*='key-skill'] span, [class*='chip'] span, "
        ".chip-container span, [class*='keySkills'] span"
    )
    skills = ", ".join(e.get_text(strip=True) for e in skill_els if e.get_text(strip=True)) or "NULL"

    # Description (capped at 3000 chars)
    desc_el = pg.select_one(
        ".job-desc, [class*='job-description'], #job-description, "
        ".jd-desc, [class*='dang-inner-html'], .jd-info, [class*='JDC__']"
    )
    desc = re.sub(r"\s+", " ",
                  desc_el.get_text(separator=" ", strip=True)[:3000]) if desc_el else "NULL"

    # Posted date
    posted_el = pg.select_one("span[class*='jhc__stat']")
    posted = (posted_el.get_text(strip=True).replace("Posted:", "").strip() if posted_el
              else txt("time", "[class*='date']", "[class*='posted']"))

    return JobRecord(
        job_title=job_title, company_name=company, location=location,
        experience=experience, salary=salary, employment_type=emp_type,
        skills=skills, job_description=desc, posted_date=posted,
        job_url=job_url, keyword_source=keyword,
    )


def process_keyword(keyword: str, progress, task_id) -> int:
    """One browser instance handles all pages for a single keyword."""
    count  = 0
    driver = None
    try:
        driver = make_driver()
        all_urls: list[str] = []

        for pg in range(1, MAX_PAGES_PER_KEYWORD + 1):
            page_urls = get_job_urls(driver, keyword, pg)
            if not page_urls:
                break
            all_urls.extend(page_urls)

        stats.bump("jobs_discovered", len(all_urls))
        new_urls = [u for u in all_urls if is_new_url(u)]
        stats.bump("jobs_skipped", len(all_urls) - len(new_urls))

        for url in new_urls:
            try:
                record = extract_job(driver, url, keyword)
                if record:
                    append_csv(record)
                    stats.bump("jobs_scraped")
                    count += 1
                else:
                    stats.bump("jobs_failed")
                    with open(FAILED_LOG, "a", encoding="utf-8") as f:
                        f.write(url + "\n")
            except Exception as e:
                stats.bump("jobs_failed")
                logging.error(f"Detail error [{url}]: {e}")
                with open(FAILED_LOG, "a", encoding="utf-8") as f:
                    f.write(url + "\n")

    except Exception:
        logging.error(f"Keyword '{keyword}':\n{traceback.format_exc()}")
    finally:
        if driver:
            quit_driver(driver)

    progress.update(task_id, advance=1)
    return count

# ═══════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════
def main():
    # Accept optional keywords file path as CLI argument
    import sys
    kw_file = Path(sys.argv[1]) if len(sys.argv) > 1 else None

    console.print(Panel.fit(
        "[bold yellow]NAUKRI JOB SCRAPER[/bold yellow]\n"
        "[cyan]Parallel Job Extraction from Keywords[/cyan]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        border_style="yellow"
    ))
    console.print(
        "[dim]Chrome windows will appear on your taskbar — this is normal and required.[/dim]\n"
        f"[dim]Workers: {MAX_WORKERS}  |  Pages/keyword: {MAX_PAGES_PER_KEYWORD}  |  "
        f"~{MAX_PAGES_PER_KEYWORD * 20} jobs/keyword[/dim]\n"
    )

    keywords = load_keywords(kw_file)
    if not keywords:
        console.print(
            "[bold red]No keywords file found in output/.[/bold red]\n"
            "[yellow]Run  python keyword_discovery.py  first.[/yellow]"
        )
        return

    init_csv()
    t_start = time.time()

    # ── Scrape all keywords in parallel ──
    console.print(Panel.fit(
        f"[bold magenta]Job Extraction[/bold magenta]\n"
        f"[white]{len(keywords)} keywords  ·  {MAX_WORKERS} parallel browsers  ·  "
        f"up to {MAX_PAGES_PER_KEYWORD * 20} jobs/keyword[/white]",
        border_style="magenta"
    ))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[bold yellow]{task.completed}/{task.total} keywords"),
        TimeElapsedColumn(),
        console=console,
    ) as prog:
        task_id = prog.add_task("Scraping jobs...", total=len(keywords))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(process_keyword, kw, prog, task_id): kw
                       for kw in keywords}
            for fut in as_completed(futures):
                kw = futures[fut]
                try:
                    n = fut.result()
                    prog.console.log(f"[green]{kw}[/green] -> {n} new jobs")
                except Exception as e:
                    logging.error(f"Worker error '{kw}': {e}")

    save_excel()
    elapsed = time.time() - t_start

    table = Table(title="Scraping Summary", border_style="cyan", show_lines=True)
    table.add_column("Metric", style="bold white")
    table.add_column("Value",  style="bold green")
    table.add_row("Keywords processed",  str(len(keywords)))
    table.add_row("Jobs discovered",     str(stats.jobs_discovered))
    table.add_row("Jobs scraped",        str(stats.jobs_scraped))
    table.add_row("Duplicates skipped",  str(stats.jobs_skipped))
    table.add_row("Jobs failed",         str(stats.jobs_failed))
    table.add_row("Time elapsed",        f"{elapsed:.0f}s  ({elapsed/60:.1f} min)")
    table.add_row("CSV output",          str(CSV_FILE))
    table.add_row("Excel output",        str(EXCEL_FILE))
    console.print(table)
    console.print(f"\n[bold green]Done! All output files are in: {OUTPUT_DIR}[/bold green]")


if __name__ == "__main__":
    main()
