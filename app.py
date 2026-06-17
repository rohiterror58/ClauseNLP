from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from pymongo import MongoClient
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from webdriver_manager.chrome import ChromeDriverManager
import undetected_chromedriver as uc
import requests
import requests as req
from bs4 import BeautifulSoup
import re, os, warnings, subprocess, time
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from ddgs import DDGS
import fitz  # pymupdf
import os


warnings.filterwarnings('ignore')

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})


SUMMARY_MODE   = os.environ.get('SUMMARY_MODE', 'ollama')
OLLAMA_URL     = 'http://localhost:11434/api/generate'
OLLAMA_MODEL   = 'llama3.2:3b'
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', 'paste_your_gemini_key_here')
MODEL_PATH     = 'tos_risk_model_2'
MONGO_URI      = 'mongodb://localhost:27017/'
MONGO_DB       = 'ClausNLP_DB'
MONGO_COL      = 'companies'

# OLLAMA — auto start + warmup
def start_ollama():
    try:
        req.get('http://localhost:11434', timeout=3)
        print('Ollama already running!')
        return True
    except:
        pass
    print('Starting Ollama...')
    subprocess.Popen(['ollama','serve'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for i in range(30):
        time.sleep(1)
        try:
            req.get('http://localhost:11434', timeout=2)
            print('Ollama started!')
            return True
        except:
            print(f'  Waiting... ({i+1}s)', end='\r')
    print('Could not start Ollama.')
    return False


def warmup_model():
    print(f'Loading {OLLAMA_MODEL} into memory...')
    try:
        r = req.post(OLLAMA_URL, json={'model': OLLAMA_MODEL, 'prompt': 'say ok', 'stream': False}, timeout=300)
        if r.status_code == 200:
            print(f'{OLLAMA_MODEL} ready!')
            return True
        print(f'Model load failed: {r.status_code}')
        return False
    except Exception as e:
        print(f'Warmup failed: {e}')
        return False

# LOAD DISTILBERT
DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
print(f'Device: {DEVICE}')
tokenizer = AutoTokenizer.from_pretrained(MODEL_PATH)
clf_model = AutoModelForSequenceClassification.from_pretrained(MODEL_PATH).to(DEVICE)
clf_model.eval()
print(f'Classifier loaded: {MODEL_PATH}')

# MONGODB
try:
    mongo_client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    mongo_client.server_info()
    db_mongo  = mongo_client[MONGO_DB]
    companies = db_mongo[MONGO_COL]
    companies.create_index('company_name', unique=True)
    print(f'MongoDB connected: {MONGO_DB}.{MONGO_COL}')
except Exception as e:
    print(f'MongoDB connection failed: {e}')
    print('Start MongoDB with: mongod')
    exit(1)


def find_in_database(name):
    return companies.find_one({'company_name': name.strip().lower()}, {'_id': 0})


def save_to_database(name, website, tos_url):
    doc = {
        'company_name':  name.strip().lower(),
        'display_name':  name.strip(),
        'website':       str(website).strip(),
        'tos_url':       tos_url.strip(),
        'last_analyzed': datetime.now().strftime('%Y-%m-%d %H:%M')
    }
    companies.update_one({'company_name': name.strip().lower()}, {'$set': doc}, upsert=True)
    print(f'MongoDB saved: {name}')


def delete_from_database(name):
    result = companies.delete_one({'company_name': name.strip().lower()})
    return result.deleted_count > 0

# DISCOVERY ENGINE
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.5',
}
SESSION = requests.Session()
SESSION.headers.update(HEADERS)

TOS_PATHS = [
    '/terms','/terms-of-service','/terms-of-use','/tos','/legal/terms',
    '/legal','/policies/terms','/policies/user-agreement','/en/terms','/about/terms',
    '/terms.html','/terms-conditions','/user-agreement','/legal/user-agreement',
    '/policies'
    '/privacy',
    '/privacy-policy',
    '/privacy-notice',
    '/cookie-policy',
    '/cookies',
    '/legal/privacy'
]

TOS_KEYWORDS = [
    'terms of service','terms of use','terms and conditions',
    'user agreement','terms & conditions','terms','tos',
    'privacy policy','privacy notice','personal data',
    'we collect','cookie policy','cookies','Law Enforcement'
]

KNOWN_DOMAINS = {
    'tor project':'torproject.org','torproject':'torproject.org',
    'wikipedia':'wikipedia.org','mozilla':'mozilla.org',
    'firefox':'mozilla.org','wordpress':'wordpress.org',
    'signal':'signal.org','telegram':'telegram.org',
    'archive':'archive.org','internet archive':'archive.org',
    'zoom':'zoom.us','notion':'notion.so',
    'twitch':'twitch.tv','npm':'npmjs.com',
    'proton':'proton.me','protonmail':'proton.me',
    'duck duck go':'duckduckgo.com','duckduckgo':'duckduckgo.com',
    'github':'github.com','gitlab':'gitlab.com',
    'instagram':'instagram.com','facebook':'facebook.com',
    'meta':'facebook.com','google':'google.com',
    'youtube':'youtube.com','twitter':'twitter.com',
    'x':'twitter.com','tiktok':'tiktok.com',
    'reddit':'reddit.com','snapchat':'snapchat.com',
    'linkedin':'linkedin.com','pinterest':'pinterest.com',
    'whatsapp':'whatsapp.com','spotify':'spotify.com',
    'netflix':'netflix.com','discord':'discord.com',
    'slack':'slack.com','dropbox':'dropbox.com',
    'paypal':'paypal.com','stripe':'stripe.com',
    'shopify':'shopify.com','airbnb':'airbnb.com',
    'uber':'uber.com','lyft':'lyft.com',
    'microsoft':'microsoft.com','apple':'apple.com',
    'amazon':'amazon.com','duolingo':'duolingo.com',
    'bugmenot':'bugmenot.com',
}

KNOWN_TOS_URLS = {
    'instagram':  'https://help.instagram.com/581066165581870',
    'facebook':   'https://www.facebook.com/terms.php',
    'meta':       'https://www.facebook.com/terms.php',
    'reddit':     'https://www.reddit.com/policies/privacy-policy',
    'whatsapp':   'https://www.whatsapp.com/legal/terms-of-service',
    'tiktok':     'https://www.tiktok.com/legal/page/us/terms-of-service/en',
    'youtube':    'https://www.youtube.com/t/terms',
    'google':     'https://policies.google.com/terms',
    'microsoft':  'https://www.microsoft.com/en-us/servicesagreement',
    'apple':      'https://www.apple.com/legal/internet-services/itunes/us/terms.html',
    'amazon':     'https://www.amazon.com/gp/help/customer/display.html?nodeId=508088',
    'twitter':    'https://twitter.com/en/tos',
    'snapchat':   'https://snap.com/en-US/terms',
    'spotify':    'https://www.spotify.com/legal/end-user-agreement/',
    'netflix':    'https://help.netflix.com/legal/termsofuse',
    'discord':    'https://discord.com/terms',
    'slack':      'https://slack.com/terms-of-service',
    'linkedin':   'https://www.linkedin.com/legal/user-agreement',
    'pinterest':  'https://policy.pinterest.com/en/terms-of-service',
    'twitch':     'https://www.twitch.tv/p/legal/terms-of-service/',
    'airbnb':     'https://www.airbnb.com/help/article/2908',
    'paypal':     'https://www.paypal.com/us/legalhub/useragreement-full',
    'dropbox':    'https://www.dropbox.com/terms',
    'uber':       'https://www.uber.com/legal/en/document/?name=general-terms-of-use',
    'zoom':       'https://explore.zoom.us/en/terms/',
    'notion':     'https://www.notion.so/Terms-and-Privacy-28ffdd083dc3473e9c2da6ec011b58ac',
    'github':     'https://docs.github.com/en/site-policy/github-terms/github-terms-of-service',
    'wikipedia':  'https://foundation.wikimedia.org/wiki/Policy:Terms_of_Use',
    'tor project':'https://www.torproject.org/about/legal/',
    'torproject': 'https://www.torproject.org/about/legal/',
    'duolingo':   'https://www.duolingo.com/terms',
    'telegram':   'https://telegram.org/tos',
    'signal':     'https://signal.org/legal/',
    'mozilla':    'https://www.mozilla.org/en-US/about/legal/terms/mozilla/',
    'wordpress':  'https://wordpress.com/tos/',
    'shopify':    'https://www.shopify.com/legal/terms',
    'stripe':     'https://stripe.com/legal/ssa',
    'duckduckgo': 'https://duckduckgo.com/terms',
    'duck duck go':'https://duckduckgo.com/terms',
    'proton':     'https://proton.me/legal/terms',
    'protonmail': 'https://proton.me/legal/terms',
    'lyft':       'https://www.lyft.com/terms',
    'gitlab':     'https://about.gitlab.com/terms/',
    'npm':        'https://docs.npmjs.com/policies/terms',
    'bugmenot':   'https://bugmenot.com/tos.php',
}

TLD_VARIANTS = ['.com','.org','.net','.io','.co','.app','.dev','.ai','.pw','.ch','.us','.me','.info','.xyz','.online','.site','.tech','.store','.world']

# CLOUDFLARE DETECTION HELPERS

# Domains known to use Cloudflare or aggressive bot protection
CLOUDFLARE_DOMAINS = {
    'bugmenot.com', 'bugmenot.com',
}

CF_INDICATORS = [
    'cf-browser-verification',
    'challenge-platform',
    'ray id',
    'cloudflare',
    'just a moment',          # Cloudflare challenge page title
    'enable javascript',
    'checking your browser',
    'ddos-guard',
    'please wait',
    '_cf_chl',
    'turnstile',
]


def is_cloudflare_blocked(response_text, status_code):
    """Return True if the page looks like a Cloudflare challenge / block."""
    if status_code in [403, 429, 503]:
        return True
    t = response_text.lower()
    if len(response_text) < 10000:
        return any(ind in t for ind in CF_INDICATORS)
    return False


def get_domain(url):
    """Extract bare domain from URL."""
    return re.sub(r'^https?://(www\.)?', '', url).split('/')[0].split('?')[0]


def needs_browser(url, response_text='', status_code=200):
    """Decide whether to fall back to undetected Chrome."""
    domain = get_domain(url)
    if domain in CLOUDFLARE_DOMAINS:
        return True
    if response_text and is_cloudflare_blocked(response_text, status_code):
        return True
    return False

# UNDETECTED CHROME — Cloudflare bypass scraper

def _get_chrome_major_version():
    """Detect the installed Chrome major version number automatically."""
    import subprocess, re
    try:
        # Windows
        result = subprocess.run(
            ['reg', 'query',
             r'HKEY_CURRENT_USER\Software\Google\Chrome\BLBeacon',
             '/v', 'version'],
            capture_output=True, text=True
        )
        m = re.search(r'(\d+)\.\d+\.\d+\.\d+', result.stdout)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    try:
        # Linux / Mac fallback
        result = subprocess.run(
            ['google-chrome', '--version'],
            capture_output=True, text=True
        )
        m = re.search(r'(\d+)\.\d+', result.stdout)
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return None          # let uc auto-detect if both fail


def _make_uc_driver():
    """Create an undetected Chrome driver (headless), pinned to the installed Chrome version."""
    options = uc.ChromeOptions()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(
        '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/146.0.0.0 Safari/537.36'
    )
    chrome_ver = _get_chrome_major_version()
    if chrome_ver:
        print(f'  [Browser] Detected Chrome {chrome_ver} — pinning ChromeDriver to match.')
        driver = uc.Chrome(options=options, use_subprocess=True, version_main=chrome_ver)
    else:
        print('  [Browser] Could not detect Chrome version — letting uc auto-select.')
        driver = uc.Chrome(options=options, use_subprocess=True)
    return driver


def extract_text_with_browser(url, wait_seconds=8):
    """
    Use undetected-chromedriver to load a Cloudflare-protected page,
    wait for the challenge to resolve, then return the page text.
    """
    print(f'  [Browser] Loading: {url}')
    driver = None
    try:
        driver = _make_uc_driver()
        driver.get(url)

        # Wait for Cloudflare challenge to clear (page title changes away from "Just a moment")
        deadline = time.time() + 20
        while time.time() < deadline:
            title = driver.title.lower()
            if 'just a moment' not in title and 'checking' not in title:
                break
            time.sleep(1)

        # Extra wait for JS-rendered content
        time.sleep(wait_seconds)

        html = driver.page_source
        print(f'  [Browser] Page source received ({len(html):,} chars)')

        soup = BeautifulSoup(html, 'html.parser')
        for tag in soup(['script', 'style', 'nav', 'footer', 'header',
                         'aside', 'figure', 'img', 'noscript']):
            tag.decompose()

        text = re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()
        print(f'  [Browser] Extracted {len(text):,} characters.')
        return text if len(text) > 300 else None

    except Exception as e:
        print(f'  [Browser] Error: {e}')
        return None
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def find_tos_url_with_browser(url):
    """
    Open a Cloudflare-protected homepage with undetected Chrome,
    then scrape all ToS-like links from the rendered page.
    """
    print(f'  [Browser] Scanning links on: {url}')
    driver = None
    try:
        driver = _make_uc_driver()
        driver.get(url)

        deadline = time.time() + 20
        while time.time() < deadline:
            if 'just a moment' not in driver.title.lower():
                break
            time.sleep(1)

        time.sleep(5)

        html   = driver.page_source
        domain = get_domain(url)
        soup   = BeautifulSoup(html, 'html.parser')
        found  = []
        for link in soup.find_all('a', href=True):
            href = link.get('href', '').lower()
            text = link.get_text().lower().strip()
            if any(k in href for k in ['terms', 'tos', 'legal', 'conditions', 'privacy']) or \
               any(k in text for k in TOS_KEYWORDS):
                if href.startswith('http'):
                    found.append(href)
                elif href.startswith('/'):
                    found.append(f'https://{domain}{href}')
        return list(dict.fromkeys(found))   # deduplicated, order preserved

    except Exception as e:
        print(f'  [Browser] Link-scan error: {e}')
        return []
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

# CANDIDATE DOMAINS + DISCOVERY

def get_candidate_domains(name):
    n = name.strip().lower()
    if '.' in n and ' ' not in n:
        return [n.replace('https://','').replace('http://','').replace('www.','').split('/')[0]]
    if n in KNOWN_DOMAINS:
        return [KNOWN_DOMAINS[n]]
    for k, v in KNOWN_DOMAINS.items():
        if len(k) > 2 and k == n:
            return [v]
    base = re.sub(r'[^a-z0-9]', '', n)
    return [f'{base}{tld}' for tld in TLD_VARIANTS]


def is_tos_page(text):
    if not text or len(text) < 300:
        return False
    tos_kws = [
        'terms of service', 'terms of use', 'user agreement',
        'terms and conditions', 'by using', 'you agree', 'prohibited',
    ]
    privacy_kws = [
        'privacy policy', 'privacy notice', 'personal data',
        'we collect', 'data protection', 'cookie policy', 'cookies','Law Enforcement',
    ]
    tos_count     = sum(1 for k in tos_kws     if k in text.lower())
    privacy_count = sum(1 for k in privacy_kws if k in text.lower())
    return tos_count >= 2 or privacy_count >= 3


def safe_get(url, timeout=4):
    try:
        return SESSION.get(url, timeout=timeout, allow_redirects=True, verify=True)
    except:
        return None


def try_url(url):
    r = safe_get(url)
    if r and r.status_code == 200 and is_tos_page(r.text):
        return r.text
    return None


def find_tos_via_paths(domains):
    urls = [f'https://{d}{p}' for d in domains[:2] for p in TOS_PATHS]
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(try_url, url): url for url in urls}
        for future in as_completed(futures):
            if future.result():
                url = futures[future]
                print(f'  Found via path scan: {url}')
                for f in futures: f.cancel()
                return url
    return None


def find_tos_via_homepage(domains):
    for domain in domains[:1]:
        r = safe_get(f'https://{domain}', timeout=6)
        if not r or r.status_code != 200:
            continue
        final_domain = r.url.split('/')[2].replace('www.','')
        soup = BeautifulSoup(r.text, 'html.parser')
        candidates = []
        for link in soup.find_all('a', href=True):
            href = link.get('href','').lower()
            text = link.get_text().lower().strip()
            if any(k in href for k in ['terms','tos','legal','conditions','privacy']) or \
               any(k in text for k in TOS_KEYWORDS):
                full = href if href.startswith('http') else \
                       f'https://{final_domain}{href}' if href.startswith('/') else None
                if full:
                    candidates.append(full)
        if candidates:
            with ThreadPoolExecutor(max_workers=10) as ex:
                futures = {ex.submit(try_url, url): url for url in candidates[:10]}
                for future in as_completed(futures):
                    if future.result():
                        url = futures[future]
                        print(f'  Found via homepage: {url}')
                        return url
    return None


def find_tos_via_search(company_name, domains):
    """Search BOTH Google and DuckDuckGo in parallel — return first valid result."""
    queries = [
        f'"{company_name}" terms of service',
        f'{company_name} terms of service',
        f'{company_name} terms and conditions',
    ]

    def search_ddg(query):
        try:
            results = list(DDGS().text(query, max_results=8))
            return [
                r.get('href', '') for r in results
                if any(k in r.get('href', '').lower()
                       for k in ['terms', 'tos', 'legal', 'conditions', 'agreement', 'privacy'])
            ]
        except:
            return []

    def search_google(query):
        try:
            from googlesearch import search
            results = list(search(query, num_results=8, sleep_interval=1))
            return [
                r for r in results
                if any(k in r.lower()
                       for k in ['terms', 'tos', 'legal', 'conditions', 'agreement', 'privacy'])
            ]
        except:
            return []

    for query in queries:
        print(f'  Searching: {query}')
        with ThreadPoolExecutor(max_workers=2) as ex:
            ddg_future    = ex.submit(search_ddg,    query)
            google_future = ex.submit(search_google, query)
            ddg_urls    = ddg_future.result()
            google_urls = google_future.result()

        seen = set()
        all_urls = []
        for url in ddg_urls + google_urls:
            if url and url not in seen:
                seen.add(url)
                all_urls.append(url)

        if not all_urls:
            continue

        print(f'  Found {len(ddg_urls)} DDG + {len(google_urls)} Google results — checking...')
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {ex.submit(try_url, url): url for url in all_urls}
            for future in as_completed(futures):
                if future.result():
                    url = futures[future]
                    print(f'  Found via search: {url}')
                    return url

    return None


def discover_tos_url(company_name):
    n       = company_name.strip().lower()
    domains = get_candidate_domains(company_name)
    primary = domains[0]
    print(f'Candidate domains: {domains[:3]}')

    if n in KNOWN_TOS_URLS:
        print(f'  Known ToS URL: {KNOWN_TOS_URLS[n]}')
        return KNOWN_TOS_URLS[n], primary
    for k, v in KNOWN_TOS_URLS.items():
        if len(k) > 2 and k == n:
            print(f'  Known ToS URL: {v}')
            return v, primary

    print('Method 1: Parallel path scan...')
    url = find_tos_via_paths(domains)
    if url: return url, primary

    print('Method 2: Homepage scan...')
    url = find_tos_via_homepage(domains)
    if url: return url, primary

    # ── NEW: Method 2b — Browser-based homepage scan (Cloudflare sites) ──
    print('Method 2b: Browser-based homepage scan (Cloudflare bypass)...')
    for domain in domains[:2]:
        homepage = f'https://{domain}'
        links = find_tos_url_with_browser(homepage)
        for link in links:
            text = extract_text_with_browser(link)
            if text and is_tos_page(text):
                print(f'  Found via browser scan: {link}')
                return link, primary

    print('Method 3: DDG + Google parallel search...')
    url = find_tos_via_search(company_name, domains)
    if url: return url, primary

    return None, primary

# SCRAPER + CLASSIFIER

def is_blocked(response):
    t = response.text.lower()
    l = len(response.text)
    if l < 5000:
        if 'captcha' in t: return True
        if 'access denied' in t and 'terms' not in t and 'privacy' not in t: return True
        if 'blocked' in t and 'terms' not in t: return True
    if is_cloudflare_blocked(response.text, response.status_code): return True
    return False


def extract_text(url):
    """
    Primary extractor.
    Step 1 — try fast requests-based scrape.
    Step 2 — if blocked / Cloudflare, fall back to undetected Chrome.
    """
    r = safe_get(url, timeout=12)
    if r:
        print(f'HTTP {r.status_code} → {r.url}')
        if r.status_code in [200, 301, 302] and r.text and not is_blocked(r):
            try:
                soup = BeautifulSoup(r.text, 'lxml')
            except Exception:
                soup = BeautifulSoup(r.text, 'html.parser')
            for tag in soup(['script','style','nav','footer','header','aside','figure','img','noscript']):
                tag.decompose()
            text = re.sub(r'\s+', ' ', soup.get_text(separator=' ')).strip()
            if len(text) > 500:
                print(f'Extracted {len(text):,} characters (requests).')
                return text
            print('Content too short — might be blocked, trying browser...')
        else:
            print(f'Blocked or bad status ({r.status_code}) — trying browser...')
    else:
        print('Request failed — trying browser...')

    # ── Cloudflare / JS-rendered fallback ─────────────────────────────
    print('Falling back to undetected Chrome...')
    text = extract_text_with_browser(url)
    if text:
        return text

    print('All extraction methods failed.')
    return None


def split_clauses(text):
    sents = re.split(r'(?<=[.!?]) +', text)
    return [s.strip() for s in sents if len(s.split()) > 6][:300]


def classify_clauses_fast(clauses):
    risky, moderate, safe = [], [], []
    batch_size = 16
    for i in range(0, len(clauses), batch_size):
        batch  = clauses[i:i+batch_size]
        inputs = tokenizer(batch, return_tensors='pt', truncation=True,
                           padding=True, max_length=128).to(DEVICE)
        with torch.no_grad():
            out = clf_model(**inputs)
        probs  = torch.nn.functional.softmax(out.logits, dim=1)
        labels = torch.argmax(probs, dim=1).tolist()
        for clause, label in zip(batch, labels):
            if label == 2:   risky.append(clause)
            elif label == 1: moderate.append(clause)
            else:            safe.append(clause)
    return risky, moderate, safe

# FALLBACK SUMMARY
def generate_fallback_summary(risky, moderate, safe):
    JARGON = {
        'terminate':   '**Account:** They can delete/block your account without warning.',
        'third party': '**Data sharing:** Your data may be shared with other companies.',
        'collect':     '**Data:** The company collects your personal information.',
        'track':       '**Tracking:** Your activity is monitored.',
        'arbitration': '**Legal:** You may not be able to sue them in court.',
        'indemnif':    '**Liability:** You may owe them money if something goes wrong.',
        'irrevocable': '**Content:** They may keep rights to your content forever.',
        'perpetual':   '**Content:** They can use what you post forever.',
        'liability':   '**Responsibility:** They limit what they owe you.',
        'cookies':     '**Tracking:** The site uses cookies to track you.',
    }
    warnings_list, seen = [], set()
    for clause in risky[:8] + moderate[:5]:
        cl = clause.lower()
        for kw, txt in JARGON.items():
            if kw in cl and txt not in seen:
                warnings_list.append(f'* {txt}')
                seen.add(txt)
                break
    return {
        'plain_english_summary': 'Ollama unavailable — keyword-based summary below.',
        'key_warnings':  '\n'.join(warnings_list) or 'No major warnings found.',
        'whats_normal':  '* Standard usage policies apply.',
        'verdict':       'Review the warnings above before agreeing.'
    }

# OLLAMA / GEMINI SUMMARY

def generate_ai_summary(company_name, risky, moderate, safe, risk_score, risk_label):
    rt = '\n'.join(f'- {c}' for c in risky[:8])    or 'None.'
    mt = '\n'.join(f'- {c}' for c in moderate[:5]) or 'None.'
    st = '\n'.join(f'- {c}' for c in safe[:3])     or 'None.'

    prompt = f"""You are a plain English explainer for Terms of Service agreements.

Analyze these clauses from {company_name}'s Terms of Service and write a short clear report.
Every point must come directly from the clauses below. Do not add anything else.
STRICT RULES:
- Never use legal words like: terminate, indemnify, arbitration, perpetual, irrevocable, liability, intellectual property, jurisdiction, warranted, sublicense, waive, damages, or remedy
- If you must mention a legal concept, immediately explain it in brackets like: arbitration [meaning you cannot sue them in court]
- Write like you are explaining to a friend, not writing a legal document
- Be direct and honest — if something is bad for the user, say so clearly
- Do not soften bad clauses or make them sound acceptable when they are not
- Do not write introductory phrases like "In summary" or "This document states"
- Never repeat the same point twice
- IMPORTANT: A LICENSE is NOT the same as OWNERSHIP. If a clause says the company gets a "license to use" your content it means they can use it but YOU still own it. Never say the company "owns" your content unless the clause explicitly uses the word "owns" or "ownership"
- IMPORTANT: If a clause says "non-exclusive license" it means the company can use your content but you keep full ownership and can still use it yourself and delete it anytime
- Never say the user "gives up ownership" of their content.
  The correct phrase is "you give them permission to use your content but you keep ownership"

HERE ARE THE CLAUSES FOUND IN THE {company_name} TERMS OF SERVICE:

HIGH RISK CLAUSES (these can seriously affect your rights):
{rt}

MODERATE RISK CLAUSES (these are worth knowing about):
{mt}

SAFE CLAUSES (these are standard and normal):
{st}

OVERALL RISK SCORE: {risk_score:.1f} out of 100
RISK LEVEL: {risk_label}

Now write your response using EXACTLY these 4 headings.
Each heading must start with ## and be on its own line.
Do not add any text before the first heading.

## Plain English Summary
Write 4 sentences explaining what {company_name}'s Terms of Service actually means for the user.
Cover: what data they collect, what they can do with your account, what rights you give up, and what happens to content you post.
Write it as if you are telling a friend what they just agreed to.
Use simple words. No jargon.

## Key Warnings
List the most important things the user should know about.
Each warning must follow this exact format:
- **[Topic]:** One clear sentence explaining what it means and why it matters to you personally.
Write at least 4 warnings if the clauses support it.
Focus on what directly affects the user — account control, data, money, legal rights, content ownership.

## Whats Normal
List the clauses that are standard and not a concern.
Each point must follow this format:
- **[Topic]:** One sentence explaining why this clause is normal and acceptable.
Write 3 to 4 points.

## Verdict
Write exactly 2 sentences.
First sentence: clearly state whether this ToS is safe, needs caution, or is seriously concerning — and why.
Second sentence: give one specific piece of advice to the user about what to watch out for or what action to take."""

    # ── SHARED SECTION EXTRACTOR ─────────────────────────────────────
    def ex(heading):
        m = re.search(
            rf'##\s*{re.escape(heading)}\s*\n(.*?)(?=\n##\s|\Z)',
            full, re.DOTALL | re.IGNORECASE
        )
        return m.group(1).strip() if m else ''

    def parse_result(full):
        if not full:
            return generate_fallback_summary(risky, moderate, safe)
        result = {
            'plain_english_summary': ex('Plain English Summary'),
            'key_warnings':          ex('Key Warnings'),
            'whats_normal':          ex('Whats Normal'),
            'verdict':               ex('Verdict'),
        }
        if not any(result.values()):
            print('Model ignored headings — returning raw response.')
            return {
                'plain_english_summary': full.strip(),
                'key_warnings': '', 'whats_normal': '', 'verdict': ''
            }
        return result

    # ── OLLAMA (local) ───────────────────────────────────────────────
    if SUMMARY_MODE == 'ollama':
        try:
            print('Sending to Ollama...')
            response = req.post(
                OLLAMA_URL,
                json={
                    'model':   OLLAMA_MODEL,
                    'prompt':  prompt,
                    'stream':  False,
                    'options': {'temperature': 0.3, 'num_predict': 1024}
                },
                timeout=180
            )
            if response.status_code != 200:
                print(f'Ollama HTTP error: {response.status_code}')
                return generate_fallback_summary(risky, moderate, safe)
            full = response.json().get('response', '').strip()
            print(f'Ollama responded ({len(full)} chars)')
            return parse_result(full)

        except req.exceptions.Timeout:
            print('Ollama timed out — using fallback.')
            return generate_fallback_summary(risky, moderate, safe)
        except Exception as e:
            print(f'Ollama error: {e}')
            return generate_fallback_summary(risky, moderate, safe)

    # ── api summary (production) ──────────────────────────────────────────
    elif SUMMARY_MODE == 'gemini':
        try:
            import google.generativeai as genai
            print('Sending to Gemini...')
            genai.configure(api_key=GEMINI_API_KEY)
            model    = genai.GenerativeModel('gemini-2.0-flash')
            response = model.generate_content(prompt)
            full     = response.text.strip()
            print(f'Gemini responded ({len(full)} chars)')
            return parse_result(full)

        except Exception as e:
            print(f'Gemini error: {e}')
            return generate_fallback_summary(risky, moderate, safe)

    # ── FALLBACK ─────────────────────────────────────────────────────
    else:
        print(f'Unknown SUMMARY_MODE: {SUMMARY_MODE} — using fallback.')
        return generate_fallback_summary(risky, moderate, safe)

# PDF EXTRACTION
def extract_text_from_pdf(pdf_file):
    try:
        if isinstance(pdf_file, bytes):
            doc = fitz.open(stream=pdf_file, filetype='pdf')
        else:
            doc = fitz.open(pdf_file)
        text = ''
        for page in doc:
            text += page.get_text()
        doc.close()
        text = re.sub(r'\s+', ' ', text).strip()
        print(f'Extracted {len(text):,} characters from PDF.')
        return text if text else None
    except Exception as e:
        print(f'PDF extraction failed: {e}')
        return None
    
# CORE ANALYSIS
def run_analysis(text, company_name, tos_url=''):
    clauses = split_clauses(text)
    if not clauses:
        return {'error': 'No valid clauses found.'}
    print(f'Classifying {len(clauses)} clauses...')
    risky, moderate, safe = classify_clauses_fast(clauses)
    total      = len(clauses)
    risk_score = ((len(risky)*1.0) + (len(moderate)*0.5)) / total * 100
    risk_label = 'Safe' if risk_score < 50 else ('Moderate' if risk_score <= 55 else 'High')
    print(f'Risk Score: {risk_score:.1f}/100 | {risk_label}')
    print('Generating summary...')
    summary = generate_ai_summary(company_name, risky, moderate, safe, risk_score, risk_label)
    return {
        'company':    company_name,
        'tos_url':    tos_url,
        'risk_score': round(risk_score, 2),
        'risk_label': risk_label,
        'counts':     {'total': total, 'risky': len(risky), 'moderate': len(moderate), 'safe': len(safe)},
        'summary':    summary,
    }


def analyze_company(company_name):
    company_name = company_name.strip()
    print(f'\n{"="*65}\n  Analyzing: {company_name}\n{"="*65}')

    entry = find_in_database(company_name)
    if entry and entry.get('tos_url'):
        tos_url = entry['tos_url']
        website = entry.get('website', '')
        print(f'Found in database: {tos_url}')
    else:
        print('Not in database — discovering ToS URL...')
        tos_url, website = discover_tos_url(company_name)
        if not tos_url:
            return {'error': f'Could not find ToS for "{company_name}". Try a different spelling.'}

    print(f'Scraping: {tos_url}')
    text = extract_text(tos_url)
    if not text:
        print('Known URL failed — trying DDG as fallback...')
        domains  = get_candidate_domains(company_name)
        fallback = find_tos_via_search(company_name, domains)
        if fallback:
            text = extract_text(fallback)
            if text:
                tos_url = fallback
    if not text:
        return {'error': 'Could not extract ToS content. Site may be blocking scrapers.'}

    save_to_database(company_name, website, tos_url)
    return run_analysis(text, company_name, tos_url)

# FLASK ROUTES

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/analyze', methods=['POST'])
def analyze():
    data = request.get_json()
    if not data or not data.get('company'):
        return jsonify({'error': 'Company name is required.'}), 400
    result = analyze_company(data['company'].strip())
    if 'error' in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route('/analyze-pdf', methods=['POST'])
def analyze_pdf_route():
    if 'file' not in request.files:
        return jsonify({'error': 'No PDF file uploaded.'}), 400
    file         = request.files['file']
    company_name = request.form.get('company', file.filename.replace('.pdf','')).strip()
    text         = extract_text_from_pdf(file.read())
    if not text:
        return jsonify({'error': 'Could not extract text from PDF. Make sure it is not a scanned image.'}), 400
    result = run_analysis(text, company_name, tos_url='PDF upload')
    if 'error' in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route('/companies', methods=['GET'])
def get_companies():
    return jsonify(list(companies.find({}, {'_id': 0})))


@app.route('/companies/<company_name>', methods=['DELETE'])
def delete_company(company_name):
    if delete_from_database(company_name):
        return jsonify({'message': f'"{company_name}" deleted successfully.'})
    return jsonify({'error': f'"{company_name}" not found.'}), 404


@app.route('/result/<company_name>', methods=['GET'])
def get_result(company_name):
    entry = find_in_database(company_name)
    if not entry:
        return jsonify({'error': f'"{company_name}" not found.'}), 404
    return jsonify(entry)

# START SERVER
if __name__ == '__main__':
    print('\n' + '='*50)
    print('  ClauseNLP — Starting up...')
    print('='*50)
    if start_ollama():
        warmup_model()
    print('\nServer running at: http://localhost:5000')
    print('='*50 + '\n')
    app.run(debug=False, port=5000, host='0.0.0.0')
