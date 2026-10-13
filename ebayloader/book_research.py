"""Book identification and research helpers for EbayLoader."""
from __future__ import annotations
import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlencode
import requests

TIMEOUT = 12
HEADERS = {"User-Agent": "EbayLoader/0.2 (book listing research)"}

def normalize_isbn(value: str) -> str:
    return re.sub(r"[^0-9Xx]", "", value or "").upper()

def valid_isbn(value: str) -> bool:
    isbn = normalize_isbn(value)
    if len(isbn) == 10:
        return sum((10-i) * (10 if c == "X" else int(c)) for i, c in enumerate(isbn)) % 11 == 0
    if len(isbn) == 13 and isbn.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(isbn[:12]))
        return (10-total % 10) % 10 == int(isbn[-1])
    return False

def extract_isbns(text: str) -> List[str]:
    candidates = re.findall(r"(?i)(?:ISBN(?:-1[03])?\s*:?\s*)?((?:97[89][\s-]?)?\d[\dXx\s-]{8,20}\d|[\dXx][\dXx\s-]{8,20})", text or "")
    found = []
    for candidate in candidates:
        isbn = normalize_isbn(candidate)
        if valid_isbn(isbn) and isbn not in found:
            found.append(isbn)
    return found

def _get_json(url: str, params: Optional[dict] = None) -> dict:
    response = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()

def research_isbn(isbn: str) -> Dict[str, Any]:
    isbn = normalize_isbn(isbn)
    if not valid_isbn(isbn):
        raise ValueError("Enter a valid ISBN-10 or ISBN-13.")
    result: Dict[str, Any] = {"isbn": isbn, "sources": [], "metadata": {}}
    try:
        data = _get_json(f"https://openlibrary.org/isbn/{isbn}.json")
        mapping = {"title":"title", "publish_date":"publication_date", "number_of_pages":"pages", "publishers":"publishers", "authors":"author_keys", "works":"work_keys"}
        for src, dst in mapping.items():
            if data.get(src):
                result["metadata"][dst] = data[src]
        authors = []
        for author in (data.get("authors") or [])[:5]:
            key = author.get("key") if isinstance(author, dict) else None
            if key:
                try:
                    name = _get_json("https://openlibrary.org" + key + ".json").get("name", "")
                    if name:
                        authors.append(name)
                except Exception:
                    pass
        if authors:
            result["metadata"]["authors"] = authors
        if data.get("works"):
            key = (data["works"][0] or {}).get("key")
            if key:
                try:
                    work = _get_json("https://openlibrary.org" + key + ".json")
                    desc = work.get("description")
                    if desc:
                        result["metadata"]["summary"] = desc.get("value", "") if isinstance(desc, dict) else desc
                except Exception:
                    pass
        result["sources"].append({"source":"Open Library","url":f"https://openlibrary.org/isbn/{isbn}","status":"match","note":"ISBN record found; verify exact edition and format."})
    except Exception as exc:
        result["sources"].append({"source":"Open Library","url":f"https://openlibrary.org/isbn/{isbn}","status":"unavailable","note":str(exc)[:180]})
    try:
        data = _get_json("https://www.googleapis.com/books/v1/volumes", {"q":"isbn:"+isbn,"maxResults":5})
        items = data.get("items") or []
        if items:
            info = items[0].get("volumeInfo") or {}
            mapping = {"title":"title","subtitle":"subtitle","authors":"authors","publisher":"publisher","publishedDate":"publication_date","pageCount":"pages","printType":"print_type","description":"summary","language":"language","categories":"categories"}
            for src, dst in mapping.items():
                if info.get(src) and not result["metadata"].get(dst):
                    result["metadata"][dst] = info[src]
            result["sources"].append({"source":"Google Books","url":info.get("infoLink") or f"https://books.google.com/books?q=isbn:{isbn}","status":"match","note":"Matched by ISBN; confirm edition details."})
        else:
            result["sources"].append({"source":"Google Books","url":f"https://books.google.com/books?q=isbn:{isbn}","status":"no match","note":"No API match returned."})
    except Exception as exc:
        result["sources"].append({"source":"Google Books","url":f"https://books.google.com/books?q=isbn:{isbn}","status":"unavailable","note":str(exc)[:180]})
    return result

class _DDGParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.active = None
        self.capture_title = False
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "a" and "result__a" in attrs.get("class", ""):
            self.active = {"title":"","url":attrs.get("href","")}
            self.capture_title = True
    def handle_data(self, data):
        if self.active is not None and self.capture_title:
            self.active["title"] += data
    def handle_endtag(self, tag):
        if tag == "a" and self.active is not None and self.capture_title:
            self.capture_title = False
            self.results.append(self.active)
            self.active = None

def web_search(query: str, limit: int = 5) -> List[dict]:
    try:
        response = requests.get("https://html.duckduckgo.com/html/", params={"q":query}, headers=HEADERS, timeout=TIMEOUT)
        response.raise_for_status()
        parser = _DDGParser()
        parser.feed(response.text)
        return parser.results[:limit]
    except Exception:
        return []

def research_links(title: str, authors: str = "", isbn: str = "") -> List[dict]:
    query = " ".join(x for x in (title, authors, isbn) if x).strip() or isbn or "book"
    encoded = quote_plus(query)
    return [
        {"source":"Publisher websites","url":f"https://www.google.com/search?q={encoded}+publisher+official","note":"Find the publisher's official edition page."},
        {"source":"General web search","url":f"https://www.google.com/search?q={encoded}","note":"Cross-check edition, format and publication details."},
        {"source":"eBay active listings","url":"https://www.ebay.com.au/sch/"+urlencode({"_nkw":query}),"note":"Compare asking prices; active prices are not sold prices."},
        {"source":"eBay sold/completed listings","url":"https://www.ebay.com.au/sch/"+urlencode({"_nkw":query,"LH_Sold":"1","LH_Complete":"1"}),"note":"Review sold/completed results manually; coverage varies."},
        {"source":"Google Books ISBN search","url":f"https://books.google.com/books?q=isbn:{quote_plus(isbn)}","note":"Secondary bibliographic cross-check."},
    ]
