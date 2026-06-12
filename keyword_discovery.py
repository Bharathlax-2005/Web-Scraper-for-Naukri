"""
NAUKRI KEYWORD DISCOVERY
========================
Opens Naukri.com and types every letter a-z into the search box.
Captures all autosuggest dropdown keywords and saves them to:

    output/keywords_TIMESTAMP.json

Run this ONCE. Then use naukri_scraper.py to scrape jobs.

Usage:
    python keyword_discovery.py

Requirements:
    pip install undetected-chromedriver selenium rich
"""

import sys, json, time, logging, traceback
from datetime import datetime
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException

console = Console()

BASE_DIR   = Path(__file__).parent
OUTPUT_DIR = BASE_DIR / "output"
LOGS_DIR   = BASE_DIR / "logs"
OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

TIMESTAMP     = datetime.now().strftime("%Y%m%d_%H%M%S")
KEYWORDS_FILE = OUTPUT_DIR / f"keywords_{TIMESTAMP}.json"

logging.basicConfig(
    filename=LOGS_DIR / f"discovery_{TIMESTAMP}.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

# ── Autosuggest dropdown selectors (tried in order, stops on first match) ──
SUGGEST_SELECTORS = [
    ".suggestor-container li",
    ".dropdown-list li",
    "[class*='suggestor'] li",
    "[class*='suggest'] li",
    "[class*='dropdown'] li",
    ".nI-gNb-sb__sugg-item",
    "ul[class*='suggest'] li",
    "ul[class*='auto'] li",
    ".autocomplete-list li",
]

# ── Search input selectors (tried in order) ──
INPUT_SELECTORS = [
    (By.XPATH,        "//input[@placeholder='Enter skills / designations / companies']"),
    (By.CSS_SELECTOR, "input[placeholder*='skills']"),
    (By.CSS_SELECTOR, "input[placeholder*='designations']"),
    (By.CSS_SELECTOR, ".nI-gNb-sb__input"),
    (By.CSS_SELECTOR, "input[type='text']"),
]


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
    for fn in (driver.service.stop, driver.quit):
        try:
            fn()
        except Exception:
            pass


def main():
    console.print(Panel.fit(
        "[bold cyan]NAUKRI KEYWORD DISCOVERY[/bold cyan]\n"
        "[white]Collecting job keywords from Naukri autosuggest (a-z)[/white]\n"
        f"[dim]{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}[/dim]",
        border_style="cyan"
    ))
    console.print("[dim]A Chrome window will open — do not close it.[/dim]\n")

    found: set[str] = set()
    driver = None
    t_start = time.time()

    try:
        driver = make_driver()

        console.print("  Loading https://www.naukri.com/ ...")
        driver.get("https://www.naukri.com/")
        time.sleep(4)

        # Find search box
        search_box = None
        for by, sel in INPUT_SELECTORS:
            try:
                search_box = WebDriverWait(driver, 5).until(
                    EC.presence_of_element_located((by, sel))
                )
                console.print("  [green]Search input found.[/green]")
                break
            except TimeoutException:
                continue

        if not search_box:
            console.print("[bold red]Could not find the search input. Exiting.[/bold red]")
            return

        # Type each letter and capture suggestions
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[bold green]{task.completed}/{task.total}"),
            TimeElapsedColumn(),
            console=console,
        ) as prog:
            task = prog.add_task("Typing letters...", total=26)

            for letter in "abcdefghijklmnopqrstuvwxyz":
                letter_kws: set[str] = set()
                try:
                    search_box.click()
                    time.sleep(0.3)
                    search_box.send_keys(Keys.CONTROL + "a")
                    search_box.send_keys(Keys.DELETE)
                    search_box.send_keys(letter)
                    time.sleep(1.5)

                    for sel in SUGGEST_SELECTORS:
                        for el in driver.find_elements(By.CSS_SELECTOR, sel):
                            t = el.text.strip()
                            if t and len(t) > 1:
                                letter_kws.add(t)
                        if letter_kws:
                            break

                except Exception as e:
                    logging.warning(f"Letter '{letter}': {e}")

                found.update(letter_kws)
                prog.update(
                    task, advance=1,
                    description=f"[cyan]{letter.upper()}[/cyan] -> {len(letter_kws)} suggestions"
                )

    except Exception:
        console.print("[bold red]Unexpected error during discovery.[/bold red]")
        logging.error(traceback.format_exc())
    finally:
        if driver:
            quit_driver(driver)

    if not found:
        console.print("[bold red]No keywords collected. Check logs.[/bold red]")
        return

    master = sorted(found)
    with open(KEYWORDS_FILE, "w", encoding="utf-8") as f:
        json.dump(master, f, indent=2, ensure_ascii=False)

    elapsed = time.time() - t_start
    console.print(
        f"\n[bold green]Done![/bold green]  "
        f"[bold]{len(master)}[/bold] unique keywords collected in {elapsed:.0f}s\n"
        f"[bold green]Saved ->[/bold green] {KEYWORDS_FILE}\n"
    )
    console.print(
        "[dim]Now run:[/dim]  [bold yellow]python naukri_scraper.py[/bold yellow]"
    )


if __name__ == "__main__":
    main()
