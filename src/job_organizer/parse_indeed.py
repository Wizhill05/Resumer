import json
import os
import chompjs

def extract_js_object(text, marker):
    start_idx = text.find(marker)
    if start_idx == -1:
        return None
        
    obj_start = text.find('{', start_idx)
    if obj_start == -1:
        return None
        
    brace_count = 0
    in_string = False
    escape = False
    
    for i in range(obj_start, len(text)):
        char = text[i]
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"' or char == "'":
            if not in_string:
                in_string = char
            elif in_string == char:
                in_string = False
            continue
            
        if not in_string:
            if char == '{':
                brace_count += 1
            elif char == '}':
                brace_count -= 1
                if brace_count == 0:
                    return text[obj_start:i+1]
    return None

def parse_indeed_html(file_path, output_json=None):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"{file_path} not found.")

    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    js_text = extract_js_object(content, 'window.mosaic.providerData["mosaic-provider-jobcards"]')
    
    if not js_text:
        raise ValueError("Could not find mosaic-provider-jobcards data in HTML.")

    try:
        data = chompjs.parse_js_object(js_text)
    except Exception as e:
        raise ValueError(f"Error decoding JavaScript object: {e}") from e

    results = data.get('results', [])
    if not results and 'metaData' in data:
        model = data['metaData'].get('mosaicProviderJobCardsModel', {})
        results = model.get('results', [])
    
    jobs = []

    for result in results:
        job_key = result.get('jobkey')
        title = result.get('displayTitle') or result.get('title')
        company = result.get('company')
        location = result.get('formattedLocation')
        relative_time = result.get('formattedRelativeTime')
        
        # Cleaned link construction
        clean_link = f"https://in.indeed.com/viewjob?jk={job_key}" if job_key else ""

        # Salary info if available
        salary_snippet = result.get('salarySnippet', {})
        salary = salary_snippet.get('text', '')

        jobs.append({
            'Title': title,
            'Company': company,
            'Location': location,
            'Job Key': job_key,
            'Link': clean_link,
            'Relative Time': relative_time,
            'Salary': salary
        })

    if not jobs:
        return []

    if output_json:
        write_jobs_json(jobs, output_json)
        print(f"Successfully extracted {len(jobs)} jobs to {output_json}")

    return jobs


def write_jobs_json(jobs, output_json):
    with open(output_json, 'w', encoding='utf-8') as f:
        json.dump(jobs, f, indent=4, ensure_ascii=False)

if __name__ == "__main__":
    html_file = 'src/job_organizer/sample.html'
    json_file = 'src/job_organizer/jobs.json'
    parse_indeed_html(html_file, json_file)
