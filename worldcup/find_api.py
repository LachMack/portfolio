#!/usr/bin/env python3
"""Find AiScore's internal API endpoint by looking at what URLs are referenced in the JS bundle"""
import re, json
from urllib.request import urlopen, Request

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': '*/*', 'Connection': 'close',
}

def fetch(url):
    try:
        req = Request(url, headers=HEADERS)
        return urlopen(req, timeout=10).read().decode('utf-8', errors='replace')
    except Exception as e:
        print(f'  Error fetching {url}: {e}')
        return ''

# Fetch the match page to find JS bundle URLs
print("Fetching match page...")
html = fetch('https://m.aiscore.com/match-mexico-south-africa/ezk96i3gjr2f1kn')
print(f"HTML length: {len(html)}")

# Find JS bundle URLs
js_urls = re.findall(r'src=["\'](/[^\'"]+\.js)["\']', html)
print(f"\nJS bundles found: {len(js_urls)}")
for u in js_urls[:10]:
    print(f"  https://m.aiscore.com{u}")

# Look for API base URLs in the HTML itself
api_patterns = re.findall(r'["\']https?://[^"\']*api[^"\']*["\']', html)
print(f"\nAPI URL patterns in HTML: {len(api_patterns)}")
for p in api_patterns[:10]:
    print(f"  {p}")

# Look for any URL patterns that look like data endpoints
data_patterns = re.findall(r'["\']https?://[^"\']*(?:score|match|event|incident|detail)[^"\']*["\']', html)
print(f"\nData endpoint patterns: {len(data_patterns[:10])}")
for p in data_patterns[:10]:
    print(f"  {p}")

# Check if there's an app.js with API config
app_js_urls = [u for u in js_urls if 'app' in u or 'main' in u or 'vendor' in u]
print(f"\nMain JS files: {app_js_urls[:5]}")
