"""
test_indeed_url_builder.py
==========================
Tests the Indeed URL builder with 40+ edge cases covering different
filter combinations (job type, location, salary, radius, date, query).

Run:
    uv run python src/scraping/test_indeed_url_builder.py
"""

import sys
import urllib.parse
from typing import Any

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# ── Indeed India URL builder ──────────────────────────────────────────────────

# Job type codes used by Indeed's `jt` parameter
JOB_TYPES = {
    "fulltime": "fulltime",
    "parttime": "parttime",
    "internship": "internship",
    "contract": "contract",
    "temporary": "temporary",
    "permanent": "permanent",
    "fresher": "fresher",
}

# Predefined Indian cities matching Indeed's location format
INDIA_LOCATIONS = [
    "Bengaluru, Karnataka",
    "Mumbai, Maharashtra",
    "Pune, Maharashtra",
    "Hyderabad, Telangana",
    "Chennai, Tamil Nadu",
    "Delhi",
    "New Delhi, Delhi",
    "Gurgaon, Haryana",
    "Gurugram, Haryana",
    "Noida, Uttar Pradesh",
    "Kolkata, West Bengal",
    "Ahmedabad, Gujarat",
    "Jaipur, Rajasthan",
    "Chandigarh",
    "Lucknow, Uttar Pradesh",
    "Kochi, Kerala",
    "Thiruvananthapuram, Kerala",
    "Coimbatore, Tamil Nadu",
    "Indore, Madhya Pradesh",
    "Bhopal, Madhya Pradesh",
    "Visakhapatnam, Andhra Pradesh",
    "Nagpur, Maharashtra",
    "Mysore, Karnataka",
    "Surat, Gujarat",
    "Vadodara, Gujarat",
    "Remote",
]

# Date posted filters (fromage param, in days)
DATE_POSTED = {
    "Last 24 hours": "1",
    "Last 3 days": "3",
    "Last 7 days": "7",
    "Last 14 days": "14",
}

# Radius values (in km for India)
RADIUS_OPTIONS = ["0", "5", "10", "15", "25", "50", "100"]

# Salary types — these match INR salary brackets Indeed uses
SALARY_TYPES = {
    "₹3,00,000+": "₹3,00,000",
    "₹5,00,000+": "₹5,00,000",
    "₹8,00,000+": "₹8,00,000",
    "₹10,00,000+": "₹10,00,000",
    "₹15,00,000+": "₹15,00,000",
    "₹20,00,000+": "₹20,00,000",
    "₹30,00,000+": "₹30,00,000",
}


def build_indeed_url(
    *,
    query: str = "",
    location: str = "",
    job_type: str = "",       # key from JOB_TYPES
    radius: str = "25",
    fromage: str = "",        # days: "1", "3", "7", "14"
    salary: str = "",         # raw salary string e.g. "₹3,00,000"
    start: int = 0,
) -> str:
    """Build an Indeed India search URL from filter parameters.

    All parameters are optional. The function only includes params
    that have non-empty values, keeping URLs clean.
    """
    base = "https://in.indeed.com/jobs"
    params: list[tuple[str, str]] = []

    SC_CODES = {
        "internship": "0kf:attr(VDTG7);",
        "fulltime": "0kf:attr(DSQF7);",
        "parttime": "0kf:attr(1JR19);",
        "contract": "0kf:attr(8S2R9);",
        "temporary": "0kf:attr(12B4P);",
        "fresher": "0kf:attr(FCH);",
    }

    if query.strip():
        params.append(("q", query.strip()))
    if location.strip():
        params.append(("l", location.strip()))
    if job_type and job_type in JOB_TYPES:
        params.append(("jt", JOB_TYPES[job_type]))
        if job_type in SC_CODES:
            params.append(("sc", SC_CODES[job_type]))
    if radius and radius != "25":  # 25 is default, skip if default
        params.append(("radius", radius))
    elif radius == "25":
        params.append(("radius", "25"))
    if fromage:
        params.append(("fromage", fromage))
    if salary.strip():
        sf = salary.strip()
        if not sf.endswith("+"):
            sf += "+"
        params.append(("salaryType", sf))
    if start > 0:
        params.append(("start", str(start)))

    if not params:
        return base

    return base + "?" + urllib.parse.urlencode(params)


# ── Test cases ────────────────────────────────────────────────────────────────

def test_url_builder():
    """Run 40+ test cases validating URL construction."""

    test_cases: list[dict[str, Any]] = [
        # --- Basic queries ---
        {"name": "1. Minimal: query only", "args": {"query": "python developer"}, "expect_in": ["q=python+developer"]},
        {"name": "2. Query + location", "args": {"query": "ai engineer", "location": "Bengaluru, Karnataka"}, "expect_in": ["q=ai+engineer", "l=Bengaluru"]},
        {"name": "3. Empty query", "args": {"query": ""}, "expect_in": ["indeed.com/jobs"]},
        {"name": "4. Whitespace-only query", "args": {"query": "   "}, "expect_in": ["indeed.com/jobs"]},

        # --- Job types ---
        {"name": "5. Full-time filter", "args": {"query": "data scientist", "location": "Mumbai, Maharashtra", "job_type": "fulltime"}, "expect_in": ["jt=fulltime", "sc=0kf%3Aattr%28DSQF7%29%3B"]},
        {"name": "6. Internship filter", "args": {"query": "ai engineer", "location": "Pune, Maharashtra", "job_type": "internship"}, "expect_in": ["jt=internship", "sc=0kf%3Aattr%28VDTG7%29%3B"]},
        {"name": "7. Part-time filter", "args": {"query": "web developer", "location": "Delhi", "job_type": "parttime"}, "expect_in": ["jt=parttime"]},
        {"name": "8. Contract filter", "args": {"query": "devops", "location": "Hyderabad, Telangana", "job_type": "contract"}, "expect_in": ["jt=contract"]},
        {"name": "9. Temporary filter", "args": {"query": "qa tester", "location": "Chennai, Tamil Nadu", "job_type": "temporary"}, "expect_in": ["jt=temporary"]},
        {"name": "10. Fresher filter", "args": {"query": "software engineer", "location": "Noida, Uttar Pradesh", "job_type": "fresher"}, "expect_in": ["jt=fresher"]},
        {"name": "11. Permanent filter", "args": {"query": "backend developer", "location": "Gurgaon, Haryana", "job_type": "permanent"}, "expect_in": ["jt=permanent"]},
        {"name": "12. Invalid job type (ignored)", "args": {"query": "ml engineer", "job_type": "invalid_type"}, "expect_not_in": ["jt="]},

        # --- Locations ---
        {"name": "13. Location: Bengaluru", "args": {"query": "swe", "location": "Bengaluru, Karnataka"}, "expect_in": ["l=Bengaluru"]},
        {"name": "14. Location: New Delhi", "args": {"query": "swe", "location": "New Delhi, Delhi"}, "expect_in": ["l=New+Delhi"]},
        {"name": "15. Location: Gurugram", "args": {"query": "swe", "location": "Gurugram, Haryana"}, "expect_in": ["l=Gurugram"]},
        {"name": "16. Location: Remote", "args": {"query": "swe", "location": "Remote"}, "expect_in": ["l=Remote"]},
        {"name": "17. Location: Kochi", "args": {"query": "swe", "location": "Kochi, Kerala"}, "expect_in": ["l=Kochi"]},
        {"name": "18. Location: Visakhapatnam", "args": {"query": "swe", "location": "Visakhapatnam, Andhra Pradesh"}, "expect_in": ["l=Visakhapatnam"]},
        {"name": "19. Location with comma encoding", "args": {"query": "swe", "location": "Pune, Maharashtra"}, "expect_in": ["l=Pune"]},
        {"name": "20. Empty location", "args": {"query": "swe", "location": ""}, "expect_not_in": ["l="]},

        # --- Radius ---
        {"name": "21. Radius 0 (exact)", "args": {"query": "swe", "location": "Delhi", "radius": "0"}, "expect_in": ["radius=0"]},
        {"name": "22. Radius 5", "args": {"query": "swe", "location": "Delhi", "radius": "5"}, "expect_in": ["radius=5"]},
        {"name": "23. Radius 50", "args": {"query": "swe", "location": "Delhi", "radius": "50"}, "expect_in": ["radius=50"]},
        {"name": "24. Radius 100", "args": {"query": "swe", "location": "Delhi", "radius": "100"}, "expect_in": ["radius=100"]},
        {"name": "25. Default radius 25", "args": {"query": "swe", "location": "Delhi", "radius": "25"}, "expect_in": ["radius=25"]},

        # --- Date posted ---
        {"name": "26. Last 24 hours", "args": {"query": "ai", "fromage": "1"}, "expect_in": ["fromage=1"]},
        {"name": "27. Last 3 days", "args": {"query": "ai", "fromage": "3"}, "expect_in": ["fromage=3"]},
        {"name": "28. Last 7 days", "args": {"query": "ai", "fromage": "7"}, "expect_in": ["fromage=7"]},
        {"name": "29. Last 14 days", "args": {"query": "ai", "fromage": "14"}, "expect_in": ["fromage=14"]},
        {"name": "30. No date filter", "args": {"query": "ai"}, "expect_not_in": ["fromage"]},

        # --- Salary ---
        {"name": "31. Salary ₹3,00,000+", "args": {"query": "swe", "salary": "₹3,00,000"}, "expect_in": ["salaryType=%E2%82%B93%2C00%2C000%2B"]},
        {"name": "32. Salary ₹10,00,000+", "args": {"query": "swe", "salary": "₹10,00,000"}, "expect_in": ["salaryType=%E2%82%B910%2C00%2C000%2B"]},
        {"name": "33. Salary ₹30,00,000+", "args": {"query": "swe", "salary": "₹30,00,000"}, "expect_in": ["salaryType=%E2%82%B930%2C00%2C000%2B"]},
        {"name": "34. Empty salary", "args": {"query": "swe"}, "expect_not_in": ["salaryType"]},

        # --- Pagination ---
        {"name": "35. Page 1 (start=0)", "args": {"query": "swe", "start": 0}, "expect_not_in": ["start="]},
        {"name": "36. Page 2 (start=10)", "args": {"query": "swe", "start": 10}, "expect_in": ["start=10"]},
        {"name": "37. Page 5 (start=40)", "args": {"query": "swe", "start": 40}, "expect_in": ["start=40"]},

        # --- Combined filters ---
        {"name": "38. All filters: query + loc + type + salary + radius + date", "args": {
            "query": "machine learning engineer",
            "location": "Bengaluru, Karnataka",
            "job_type": "fulltime",
            "salary": "₹15,00,000",
            "radius": "50",
            "fromage": "7",
        }, "expect_in": ["q=machine+learning+engineer", "l=Bengaluru", "jt=fulltime", "radius=50", "fromage=7", "salaryType="]},

        {"name": "39. Internship + Pune + 3 days", "args": {
            "query": "ai intern",
            "location": "Pune, Maharashtra",
            "job_type": "internship",
            "fromage": "3",
        }, "expect_in": ["jt=internship", "sc=0kf%3Aattr%28VDTG7%29%3B", "l=Pune", "fromage=3"]},

        {"name": "40. Contract + Hyderabad + high salary", "args": {
            "query": "cloud architect",
            "location": "Hyderabad, Telangana",
            "job_type": "contract",
            "salary": "₹30,00,000",
        }, "expect_in": ["jt=contract", "l=Hyderabad", "salaryType="]},

        {"name": "41. Remote + any type", "args": {
            "query": "react developer",
            "location": "Remote",
        }, "expect_in": ["l=Remote"]},

        {"name": "42. Multi-word query with special chars", "args": {
            "query": "C++ developer & ML",
            "location": "Bengaluru, Karnataka",
        }, "expect_in": ["q=C%2B%2B+developer+%26+ML"]},

        {"name": "43. Query with slash", "args": {
            "query": "frontend/backend engineer",
        }, "expect_in": ["q=frontend%2Fbackend+engineer"]},

        {"name": "44. Very long query", "args": {
            "query": "senior principal staff machine learning artificial intelligence deep learning NLP computer vision engineer",
            "location": "Mumbai, Maharashtra",
            "job_type": "fulltime",
            "salary": "₹20,00,000",
            "radius": "15",
            "fromage": "14",
        }, "expect_in": ["q=senior+principal", "jt=fulltime", "radius=15", "fromage=14"]},
    ]

    passed = 0
    failed = 0

    for tc in test_cases:
        url = build_indeed_url(**tc["args"])
        ok = True
        errors = []

        for substr in tc.get("expect_in", []):
            if substr not in url:
                ok = False
                errors.append(f"  MISSING: '{substr}'")

        for substr in tc.get("expect_not_in", []):
            if substr in url:
                ok = False
                errors.append(f"  UNWANTED: '{substr}'")

        if ok:
            passed += 1
            print(f"  [PASS] {tc['name']}")
        else:
            failed += 1
            print(f"  [FAIL] {tc['name']}")
            print(f"     URL: {url}")
            for err in errors:
                print(f"    {err}")

    print(f"\n{'='*50}")
    print(f"  Results: {passed} passed, {failed} failed out of {len(test_cases)}")
    print(f"{'='*50}")

    return failed == 0


if __name__ == "__main__":
    print("Testing Indeed URL builder...\n")
    success = test_url_builder()
    if not success:
        exit(1)
    print("\nAll tests passed!")
