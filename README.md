# Web-Scraper-for-Naukri
Scrapping Job Details from Naukri Portal for Educational Purpose

This project is designed to automatically collect job information from Naukri.com based on a list of keywords.


## Process

1. Reads keywords from a JSON file.
2. Searches Naukri using those keywords.
3. Collects job links from search result pages.
4. Visits each job page.
5. Extracts job details.
6. Removes duplicate jobs.
7. Saves the final results into Excel files.

# Technologies Used

## 1. Selenium + Undetected ChromeDriver

- Opens Chrome browser automatically.
- Visits Naukri pages.
- Loads dynamic content.
- Because of user browsing behavior.
- Helps avoid bot detection.

## 2. BeautifulSoup

- Parses HTML content.
- Extracts required information.
- Finds job links.
- Reads job details from pages.
