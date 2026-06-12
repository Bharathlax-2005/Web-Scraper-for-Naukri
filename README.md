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

## Detailed Process of the Work  
In this project, I built a Naukri job scraping system that automatically collects job information based on keywords.

The process starts by reading keywords from a JSON file. These keywords are generated from a separate keyword discovery process and act as search terms for finding jobs on Naukri.

For each keyword, the scraper opens Naukri search result pages using Selenium with Undetected ChromeDriver. I used Selenium because Naukri loads content dynamically, and a real browser is needed to properly load and render the pages.

Once the search page is loaded, BeautifulSoup is used to parse the HTML and collect all available job links from the search results. The scraper checks multiple pages for each keyword and gathers all job URLs.

After collecting the URLs, duplicate job links are removed to ensure the same job is not scraped multiple times, even if it appears under different keywords or pages.

The scraper then visits each unique job URL individually. From the job page, BeautifulSoup extracts important information such as:

Job Title
Company Name
Location
Experience Required
Salary
Employment Type
Skills Required
Job Description
Posted Date
Job URL

The final output is a raw Excel dataset containing
