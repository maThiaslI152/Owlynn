"""
Web Tools: Search + Fetch
--------------------------
web_search  : DuckDuckGo search (no API key needed)
fetch_webpage: requests + BeautifulSoup for readable page text
"""

from langchain_core.tools import tool


@tool
def web_search(query: str, news: bool = False) -> str:
    """
    Searches the web using DuckDuckGo and returns the top results.
    
    Use this to look up current information, documentation, definitions, or
    any topic the user asks about that isn't already in your knowledge.
    
    Args:
        query: A clear, specific search query string.
        news: Set to True if you are explicitly looking for CURRENT EVENTS, 
              NEWS ARTICLES, or RECENT press releases. (Uses DuckDuckGo News).
    
    Returns:
        Top search results with title, URL, and snippet for each result.
    """
    try:
        from ddgs import DDGS
        
        results = []
        with DDGS() as ddgs:
            if news:
                # Use News Search for specific articles
                for r in ddgs.news(query, max_results=4):
                    # Standardize keys to match text search structure
                    results.append({
                        "title": r.get("title", ""),
                        "href": r.get("url", ""),
                        "body": f"[{r.get('source', 'News')}] - {r.get('snippet', '')}"
                    })
            else:
                # Standard Text Search
                for r in ddgs.text(query, max_results=4):
                    results.append(r)
        
        if not results:
            return f"No results found for: \"{query}\". Try a different query or be less specific."
        
        lines = [f"🔍 {'News' if news else 'Web'} search results for: \"{query}\"", ""]
        for i, r in enumerate(results, 1):
            lines.append(f"**{i}. {r.get('title', 'No title')}**")
            lines.append(f"   URL: {r.get('href', '')}")
            lines.append(f"   {r.get('body', 'No snippet available')}")
            lines.append("")
        
        return "\n".join(lines)
    except Exception as e:
        return f"[web_search] Error: {str(e)}"


@tool
def fetch_webpage(url: str) -> str:
    """
    Fetches a webpage and returns its readable text content.
    
    Use this to read documentation, articles, or any specific URL.
    Works best for standard HTML pages. Will strip all HTML tags and
    return clean, readable text (max 5,000 characters).
    
    Args:
        url: The full URL to fetch (must include http:// or https://)
    
    Returns:
        The readable text content of the page, or an error message.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36"
        }
        
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        
        soup = BeautifulSoup(resp.text, "lxml")
        
        # Remove navigation, scripts, styles, ads
        for tag in soup(["script", "style", "nav", "footer", "header", "aside", "iframe", "noscript"]):
            tag.decompose()
        
        # Get main content — prefer <article>, <main>, <section> over raw body
        main = soup.find("article") or soup.find("main") or soup.find("section") or soup.body
        text = main.get_text(separator="\n", strip=True) if main else soup.get_text(separator="\n", strip=True)
        
        # Collapse excessive blank lines
        lines = [l for l in text.splitlines() if l.strip()]
        clean = "\n".join(lines)
        
        # Cap at 4000 chars for better context window management
        if len(clean) > 4000:
            clean = clean[:4000] + "\n\n... [content truncated for brevity]"
        
        return f"📄 Content from {url}:\n\n{clean}"
    
    except requests.exceptions.Timeout:
        return f"[fetch_webpage] Timed out fetching {url}"
    except requests.exceptions.HTTPError as e:
        return f"[fetch_webpage] HTTP error {e.response.status_code} for {url}"
    except Exception as e:
        return f"[fetch_webpage] Error: {str(e)}"
