import json
import time
import os
import re
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from bs4 import BeautifulSoup
from urllib.parse import urlparse, parse_qs

def scrape_job_descriptions(input_json, output_json):
    if not os.path.exists(input_json):
        # Fallback to csv if json not found but csv exists
        alt_csv = input_json.replace('.json', '.csv')
        if os.path.exists(alt_csv):
            import csv
            with open(alt_csv, 'r', encoding='utf-8') as f:
                jobs = list(csv.DictReader(f))
        else:
            print(f"Error: {input_json} not found.")
            return
    else:
        with open(input_json, 'r', encoding='utf-8') as f:
            jobs = json.load(f)

    if not jobs:
        print("No jobs found.")
        return

    # Selenium Setup
    chrome_options = Options()
    # Stealth settings to bypass detection
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option('useAutomationExtension', False)
    
    print("Initializing browser...")
    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
    
    # Execute stealth script
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

    try:
        # Step 1: Open the first job to trigger verification
        first_job_link = jobs[0].get('Link')
        print(f"Opening first job: {first_job_link}")
        driver.get(first_job_link)
        
        print("\n" + "="*50)
        print("ACTION REQUIRED: If a Cloudflare / Human Verification prompt appears, please solve it.")
        print("IMPORTANT: After solving, wait for the page to fully load.")
        print("If the prompt REAPPEARS, try to solve it again or check if you are being blocked.")
        print("Once you are on the job page and everything looks loaded, press ENTER in this terminal.")
        print("="*50 + "\n")
        input("Press Enter to continue...")

        # Step 2: Loop through all jobs
        for i, job in enumerate(jobs):
            # Check if already scraped
            if job.get('Description') and job['Description'] != "FAILED":
                continue

            link = job.get('Link')
            if not link:
                continue

            print(f"[{i+1}/{len(jobs)}] Scraping: {job.get('Title')} at {job.get('Company')}...")
            
            try:
                if i > 0:
                    driver.get(link)
                    # Random sleep to look more human
                    time.sleep(3 + (time.time() % 3)) # 3 to 6 seconds

                # Wait for the job description to appear
                wait = WebDriverWait(driver, 15)
                wait.until(EC.presence_of_element_located((By.ID, "jobDescriptionText")))
                
                # Parse with BeautifulSoup for robust extraction
                soup = BeautifulSoup(driver.page_source, 'lxml')
                
                # 1. Description
                desc_element = soup.find(id='jobDescriptionText')
                job['Description'] = desc_element.get_text(separator='\n', strip=True) if desc_element else ""
                
                # 2. Salary
                if not job.get('Salary'):
                    # Try to find salary on page
                    salary_div = soup.find(id='salaryInfoAndJobType')
                    if salary_div:
                        job['Salary'] = salary_div.get_text(' ', strip=True)
                    else:
                        for el in soup.find_all(attrs={'data-testid': True}):
                            tid = el.get('data-testid', '')
                            if 'salary' in tid.lower() or 'pay' in tid.lower():
                                job['Salary'] = el.get_text(' ', strip=True)
                                break

                # 3. Apply Link
                apply_container = soup.find(id='applyButtonLinkContainer')
                apply_link = ""
                if apply_container:
                    btn = apply_container.find(['a', 'button'], href=True)
                    if btn:
                        raw_href = btn.get('href', '')
                        parsed = urlparse(raw_href)
                        params = parse_qs(parsed.query)
                        jk = params.get('jk', [None])[0]
                        if jk:
                            apply_link = f'https://in.indeed.com/applystart?jk={jk}'
                        else:
                            apply_link = raw_href
                
                # Fallback to constructing apply link if we have the job key
                if not apply_link and job.get('Job Key'):
                    apply_link = f"https://in.indeed.com/applystart?jk={job['Job Key']}"
                    
                job['Apply Link'] = apply_link

                print(f"   Done. (Desc length: {len(job['Description'])})")
            except Exception as e:
                print(f"   Error on {link}: {str(e)[:100]}...")
                job['Description'] = "FAILED"
                # If the session is lost, we should break and save
                if "session" in str(e).lower() or "disconnected" in str(e).lower():
                    print("   Critical: Browser session lost. Saving progress and exiting.")
                    break

            # Optional: Intermediate save every 5 jobs
            if (i + 1) % 5 == 0:
                save_to_json(jobs, output_json)

        # Final Save
        save_to_json(jobs, output_json)
        print(f"\nSuccessfully saved all jobs with descriptions to {output_json}")

    finally:
        driver.quit()

def save_to_json(jobs, output_json):
    if not jobs:
        return
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    input_json = 'src/job_organizer/jobs.json'
    output_json = 'src/job_organizer/jobs_with_descriptions.json'
    scrape_job_descriptions(input_json, output_json)
