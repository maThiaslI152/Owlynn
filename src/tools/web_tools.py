"""
Web Tools: Search + Fetch (Overhauled)
--------------------------------------
web_search           : Metasearch (Google, Bing, DDG, etc.) via ddgs or Playwright fallback
fetch_webpage        : Static fetching via httpx + BeautifulSoup
fetch_webpage_dynamic: Dynamic fetching via Playwright
"""

import asyncio
import logging
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


async def _google_search_playwright(query: str) -> str:
    """Fallback Google search using Playwright to handle fragile selectors or CAPTCHAs."""
    from playwright.async_api import async_playwright
    from bs4 import BeautifulSoup
    
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            # Navigate to Google with search query
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            await page.goto(url, wait_until="networkidle")
            content = await page.content()
            await browser.close()
            
            soup = BeautifulSoup(content, "lxml")
            
            # Check for CAPTCHA or Bot detection
            if "captcha" in content.lower() or "unusual traffic" in content.lower():
                logger.warning("Google search blocked by CAPTCHA")
                return "[google_search_playwright] Error: Blocked by Google CAPTCHA/Bot detection."
                
            results = []
            
            # Google results usually sit in 'div.g'
            for g in soup.find_all("div", class_="g"):
                title_el = g.find("h3")
                link_el = g.find("a")
                if title_el and link_el:
                    href = link_el.get("href")
                    if href and href.startswith("http"):
                        # Extract snippet - find div for snippet or iterate children
                        # Snippets often sit in -webkit-line-clamp divs or similar
                        # We will make copies of title/link to not destroy soup, or clone
                        # But simpler is getting all text excluding title/link
                        title_text = title_el.get_text()
                        
                        # Copy 'g' and decompose title/link to get raw text snippet
                        # Wait, decomposing modifies the tree. We can just use text extraction.
                        # Using raw text for now
                        all_text = g.get_text(separator=" ", strip=True)
                        snippet = all_text.replace(title_text, "").strip()
                        
                        results.append({
                            "title": title_text,
                            "href": href,
                            "body": snippet[:200] + "..." if len(snippet) > 200 else snippet
                        })
                        
            if not results:
                # Let's try alternative selector for simple results
                # Sometimes Google shows 'kp-blk' or other things
                pass
                
            if not results:
                return f"No Google search results found for: \"{query}\" via Playwright."
                
            lines = [f"🔍 Google search results for: \"{query}\" (via Playwright)", ""]
            for i, r in enumerate(results[:5], 1):
                lines.append(f"**{i}. {r['title']}**")
                lines.append(f"   URL: {r['href']}")
                lines.append(f"   {r['body']}")
                lines.append("")
            return "\n".join(lines)
    except Exception as e:
        logger.error(f"_google_search_playwright error: {e}")
        return f"[google_search_playwright] Error: {str(e)}"


@tool
async def web_search(query: str, backend: str = "auto", news: bool = False) -> str:
    """
    Searches the web using a metasearch engine and returns top results.
    
    Use this to look up current information, documentation, definitions, or
    any topic the user asks about that isn't already in your knowledge.
    
    Args:
        query: A clear, specific search query string.
        backend: The search engine to use. Options: "auto" (default), "google", "bing", "duckduckgo", "wikipedia".
        news: Set to True if you are explicitly looking for CURRENT EVENTS, 
              NEWS ARTICLES, or RECENT press releases.
    """
    try:
        # Fallback to Playwright for Google search explicitly
        if backend.lower() == "google":
            return await _google_search_playwright(query)
            
        from ddgs import DDGS
        
        def _search():
            with DDGS() as ddgs:
                if news:
                    return ddgs.news(query, backend=backend, max_results=5)
                else:
                    return ddgs.text(query, backend=backend, max_results=5)

        # Run the synchronous ddgs search in a thread pool to avoid blocking the asyncio loop
        results = await asyncio.to_thread(_search)
        
        if not results:
            return f"No results found for: \"{query}\" using backend=\"{backend}\"."
            
        lines = [f"🔍 {'News' if news else 'Web'} search results for: \"{query}\" (Backend: {backend})", ""]
        for i, r in enumerate(results, 1):
            title = r.get("title") or r.get("name") or r.get("snippet", "No title")
            href = r.get("href") or r.get("url") or ""
            body = r.get("body") or r.get("snippet") or r.get("description") or "No snippet"
            
            lines.append(f"**{i}. {title}**")
            lines.append(f"   URL: {href}")
            lines.append(f"   {body}")
            lines.append("")
            
        return "\n".join(lines)
    except Exception as e:
        logger.error(f"web_search error: {e}")
        return f"[web_search] Error: {str(e)}"


@tool
async def fetch_webpage(url: str) -> str:
    """
    Fetches a static webpage and returns its readable text content.
    
    Use this to read documentation, articles, or any specific URL.
    Works best for standard HTML pages. Strips HTML tags and
    returns clean, readable text.
    """
    import httpx
    from bs4 import BeautifulSoup
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # Added trust_env=False to avoid some local proxy issues, and verify=True
        # We can fallback to verify=False if explicit SSL error happens
        async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True) as client:
            try:
                resp = await client.get(url)
            except httpx.ConnectError as e:
                # Workaround for general SSL errors: cert update missing on Mac python
                if "SSL" in str(e):
                    logger.warning(f"SSL error, retrying without verification for {url}")
                    async with httpx.AsyncClient(timeout=10.0, headers=headers, follow_redirects=True, verify=False) as client_unsafe:
                        resp = await client_unsafe.get(url)
                else:
                    raise e
            resp.raise_for_status()
            
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Remove navigation, scripts, styles, etc.
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()
            
        main = soup.find("article") or soup.find("main") or soup.find("section") or soup.body
        text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)
        
        lines = [l for l in text.splitlines() if l.strip()]
        clean = "\n".join(lines)
        
        if len(clean) > 4000:
            clean = clean[:4000] + "\n\n... [content truncated for brevity]"
            
        return f"📄 Content from {url}:\n\n{clean}"
        
    except httpx.HTTPStatusError as e:
        return f"[fetch_webpage] HTTP error {e.response.status_code} for {url}"
    except httpx.TimeoutException:
        return f"[fetch_webpage] Timed out fetching {url}"
    except Exception as e:
        return f"[fetch_webpage] Error: {str(e)}"


@tool
async def fetch_webpage_dynamic(url: str) -> str:
    """
    Fetches a dynamic (JavaScript-rendered) webpage and returns its text content.
    
    Use this for Single Page Applications (SPAs) or dashboards where fetch_webpage
    returns empty content due to lack of JS rendering.
    """
    try:
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()
            
            await page.goto(url, wait_until="networkidle", timeout=30000)
            content = await page.content()
            await browser.close()
            
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "lxml")
            
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
                tag.decompose()
                
            main = soup.find("article") or soup.find("main") or soup.find("section") or soup.body
            text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)
            
            lines = [l for l in text.splitlines() if l.strip()]
            clean = "\n".join(lines)
            
            if len(clean) > 4000:
                clean = clean[:4000] + "\n\n... [content truncated for brevity]"
                
            return f"📄 [Dynamic] Content from {url}:\n\n{clean}"
            
    except Exception as e:
        return f"[fetch_webpage_dynamic] Error: {str(e)}"
