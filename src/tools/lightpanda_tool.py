"""
Lightpanda Browser Tool
-----------------------
A high-performance headless browser for web scraping and automation.

Features:
- Fast JavaScript execution
- DOM manipulation
- Screenshot capture
- Cookie/session management
- Multi-page handling
"""

import json
import logging
import asyncio
from typing import Optional
from langchain_core.tools import tool

logger = logging.getLogger(__name__)

# Global browser instance (lazy-loaded)
_browser_instance = None
_browser_lock = asyncio.Lock()

async def get_lightpanda_browser():
    """Get or create a Lightpanda browser instance."""
    global _browser_instance, _browser_lock
    
    async with _browser_lock:
        if _browser_instance is None:
            try:
                # Try to import lightpanda
                from lightpanda import Browser
                _browser_instance = Browser()
                logger.info("Lightpanda browser initialized")
            except ImportError:
                logger.error("Lightpanda not installed. Install with: pip install lightpanda")
                return None
            except Exception as e:
                logger.error(f"Failed to initialize Lightpanda: {e}")
                return None
    
    return _browser_instance


@tool
async def lightpanda_fetch_page(url: str, wait_selector: Optional[str] = None, timeout: int = 30) -> str:
    """
    Fetch a webpage using Lightpanda headless browser with JavaScript execution.
    
    Better than regular fetch when:
    - The page loads content dynamically with JavaScript
    - The page requires JavaScript interaction
    - You need to wait for specific elements to load
    
    Args:
        url: The full URL to fetch (must include http:// or https://)
        wait_selector: Optional CSS selector to wait for (e.g., '.results' or '#content')
        timeout: Seconds to wait for page load (default 30)
    
    Returns:
        A formatted string with page title, URL, and rendered HTML content
    """
    try:
        browser = await get_lightpanda_browser()
        if not browser:
            return "Error: Lightpanda browser not available. Install it with: pip install lightpanda"
        
        # Validate URL
        if not url.startswith(('http://', 'https://')):
            return f"Error: URL must start with http:// or https://. Got: {url}"
        
        logger.info(f"Fetching page with Lightpanda: {url}")
        
        # Create new tab
        tab = await asyncio.wait_for(browser.new_tab(), timeout=timeout)
        
        try:
            # Navigate to URL
            await asyncio.wait_for(tab.goto(url), timeout=timeout)
            
            # Wait for selector if specified
            if wait_selector:
                logger.debug(f"Waiting for selector: {wait_selector}")
                await asyncio.wait_for(
                    tab.wait_for_selector(wait_selector),
                    timeout=timeout
                )
            else:
                # Wait for basic page load
                await asyncio.wait_for(
                    tab.wait_for_navigation(),
                    timeout=min(timeout, 10)
                )
            
            # Get page content
            title = await tab.get_title()
            content_html = await tab.get_html()
            current_url = await tab.get_url()
            
            # Truncate content if very large
            content_preview = content_html[:3000] if len(content_html) > 3000 else content_html
            truncated = len(content_html) > 3000
            
            result = f"""# Lightpanda Browser Result

**Page Title:** {title}
**URL:** {current_url}
**Rendered Content:** (JavaScript executed)

```html
{content_preview}
```

{'⚠️ Content truncated (original length: ' + str(len(content_html)) + ' chars)' if truncated else ''}

**Content Length:** {len(content_html)} characters
"""
            
            return result
            
        finally:
            # Close tab
            await tab.close()
    
    except asyncio.TimeoutError:
        return f"Error: Timeout while loading {url} (waited {timeout}s)"
    except Exception as e:
        logger.error(f"Lightpanda fetch error: {e}", exc_info=True)
        return f"Error: Failed to fetch with Lightpanda: {str(e)}"


@tool
async def lightpanda_execute_js(url: str, javascript_code: str, wait_time: int = 2) -> str:
    """
    Execute custom JavaScript on a webpage and capture the result.
    
    Useful for:
    - Extracting data from JavaScript-rendered content
    - Interacting with dynamic elements
    - Automating user actions
    - Scraping single-page applications
    
    Args:
        url: The webpage URL to load
        javascript_code: JavaScript code to execute. Should return a value or log to console.
        wait_time: Seconds to wait for JS execution (default 2)
    
    Returns:
        The result of JavaScript execution or console output
    """
    try:
        browser = await get_lightpanda_browser()
        if not browser:
            return "Error: Lightpanda browser not available"
        
        if not url.startswith(('http://', 'https://')):
            return f"Error: Invalid URL format: {url}"
        
        logger.info(f"Executing JavaScript on: {url}")
        
        tab = await asyncio.wait_for(browser.new_tab(), timeout=30)
        
        try:
            # Navigate to URL
            await asyncio.wait_for(tab.goto(url), timeout=30)
            
            # Wait for page to settle
            await asyncio.sleep(wait_time)
            
            # Execute JavaScript and capture result
            result = await tab.eval_script(javascript_code)
            
            # Convert result to string if needed
            if isinstance(result, dict) or isinstance(result, list):
                result_str = json.dumps(result, indent=2)
            else:
                result_str = str(result)
            
            return f"""# JavaScript Execution Result

**URL:** {url}
**Script:** 
```javascript
{javascript_code}
```

**Result:**
```
{result_str}
```

**Status:** ✅ Success
"""
            
        finally:
            await tab.close()
    
    except Exception as e:
        logger.error(f"JavaScript execution error: {e}", exc_info=True)
        return f"Error executing JavaScript: {str(e)}"


@tool
async def lightpanda_screenshot(url: str, wait_selector: Optional[str] = None, full_page: bool = False) -> str:
    """
    Capture a screenshot of a webpage using Lightpanda.
    
    Useful for:
    - Verifying page layout and appearance
    - Capturing dynamic content
    - Visual regression testing
    - Documenting webpage state
    
    Args:
        url: The webpage URL to screenshot
        wait_selector: CSS selector to wait for before capturing (optional)
        full_page: Capture full page or viewport only (default: viewport)
    
    Returns:
        Path to saved screenshot file and metadata
    """
    try:
        browser = await get_lightpanda_browser()
        if not browser:
            return "Error: Lightpanda browser not available"
        
        if not url.startswith(('http://', 'https://')):
            return f"Error: Invalid URL format: {url}"
        
        logger.info(f"Taking screenshot of: {url}")
        
        tab = await asyncio.wait_for(browser.new_tab(), timeout=30)
        
        try:
            # Navigate to URL
            await asyncio.wait_for(tab.goto(url), timeout=30)
            
            # Wait for selector if specified
            if wait_selector:
                await asyncio.wait_for(tab.wait_for_selector(wait_selector), timeout=30)
            else:
                await asyncio.sleep(2)  # Wait for page to render
            
            # Get screenshot filename
            import time
            from pathlib import Path
            
            screenshots_dir = Path("workspace/.screenshots")
            screenshots_dir.mkdir(parents=True, exist_ok=True)
            
            timestamp = int(time.time() * 1000)
            filename = f"screenshot_{timestamp}.png"
            filepath = screenshots_dir / filename
            
            # Take screenshot
            screenshot_data = await tab.screenshot(full_page=full_page)
            
            # Save screenshot
            with open(filepath, "wb") as f:
                f.write(screenshot_data)
            
            return f"""# Screenshot Captured

**URL:** {url}
**File:** {str(filepath)}
**Size:** {len(screenshot_data)} bytes
**Full Page:** {full_page}
**Status:** ✅ Screenshot saved

You can view the screenshot at: `{str(filepath)}`
"""
            
        finally:
            await tab.close()
    
    except Exception as e:
        logger.error(f"Screenshot error: {e}", exc_info=True)
        return f"Error capturing screenshot: {str(e)}"


@tool
async def lightpanda_extract_data(url: str, css_selectors: dict[str, str]) -> str:
    """
    Extract structured data from a webpage using CSS selectors.
    
    Useful for:
    - Web scraping with CSS selectors
    - Extracting product information
    - Pulling data from structured pages
    - Automated data collection
    
    Args:
        url: The webpage URL to scrape
        css_selectors: Dictionary mapping field names to CSS selectors
                      Example: {"title": "h1.title", "price": ".price"}
    
    Returns:
        Extracted data as JSON
    """
    try:
        browser = await get_lightpanda_browser()
        if not browser:
            return "Error: Lightpanda browser not available"
        
        if not url.startswith(('http://', 'https://')):
            return f"Error: Invalid URL format: {url}"
        
        if not isinstance(css_selectors, dict) or not css_selectors:
            return "Error: css_selectors must be a non-empty dictionary"
        
        logger.info(f"Extracting data from: {url}")
        logger.debug(f"Selectors: {css_selectors}")
        
        tab = await asyncio.wait_for(browser.new_tab(), timeout=30)
        
        try:
            # Navigate to URL
            await asyncio.wait_for(tab.goto(url), timeout=30)
            await asyncio.sleep(2)  # Wait for page to render
            
            # Extract data
            extracted = {}
            
            for field, selector in css_selectors.items():
                try:
                    # Query selector
                    elements = await tab.query_selector_all(selector)
                    
                    if not elements:
                        extracted[field] = None
                    elif len(elements) == 1:
                        # Single element - get text
                        text = await elements[0].get_text()
                        extracted[field] = text
                    else:
                        # Multiple elements - get all text
                        texts = []
                        for elem in elements:
                            text = await elem.get_text()
                            texts.append(text)
                        extracted[field] = texts
                
                except Exception as e:
                    logger.warning(f"Failed to extract '{field}' with selector '{selector}': {e}")
                    extracted[field] = f"Error: {str(e)}"
            
            return f"""# Data Extraction Result

**URL:** {url}
**Selectors Used:** {len(css_selectors)}

**Extracted Data:**
```json
{json.dumps(extracted, indent=2)}
```

**Status:** ✅ Extraction complete
"""
            
        finally:
            await tab.close()
    
    except Exception as e:
        logger.error(f"Data extraction error: {e}", exc_info=True)
        return f"Error extracting data: {str(e)}"


@tool
def lightpanda_health_check() -> str:
    """
    Check if Lightpanda browser is available and working.
    
    Returns a status report about Lightpanda availability.
    """
    try:
        import lightpanda
        version = getattr(lightpanda, '__version__', 'unknown')
        return f"""# Lightpanda Health Check

✅ **Status:** Ready

- **Library:** lightpanda
- **Version:** {version}
- **Status:** Installed and available

Available tools:
- ✅ fetch_page - Fetch and render pages with JavaScript
- ✅ execute_js - Execute custom JavaScript
- ✅ screenshot - Capture page screenshots  
- ✅ extract_data - Scrape data with CSS selectors

**Ready to use!**
"""
    except ImportError:
        return """# Lightpanda Health Check

❌ **Status:** Not installed

To install Lightpanda:
```bash
pip install lightpanda
```

After installation, these tools will be available:
- fetch_page - Fetch and render pages with JavaScript
- execute_js - Execute custom JavaScript
- screenshot - Capture page screenshots
- extract_data - Scrape data with CSS selectors
"""
    except Exception as e:
        return f"""# Lightpanda Health Check

⚠️ **Status:** Error

Error: {str(e)}

Please check your Lightpanda installation.
"""
