import asyncio
import re
import json
from typing import Optional, Dict, Any
from playwright.async_api import async_playwright, Page, Browser
from bs4 import BeautifulSoup
from app.models import ScrapedProfile
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class StripeProfileScraper:
    def __init__(self):
        self.browser: Optional[Browser] = None
        self.playwright = None

    async def start(self):
        """Initialize the browser"""
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True,
            args=[
                '--no-sandbox',
                '--disable-setuid-sandbox',
                '--disable-dev-shm-usage',
                '--disable-gpu',
                '--single-process'
            ]
        )
        logger.info("Browser started successfully")

    async def stop(self):
        """Close the browser"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser stopped")

    def parse_url(self, url: str) -> tuple[str, str]:
        """Extract username and profile code from URL"""
        pattern = r'https?://profile\.stripe\.com/([^/]+)/([A-Za-z0-9]+)/?'
        match = re.match(pattern, url)
        if match:
            return match.group(1), match.group(2)
        raise ValueError(f"Invalid URL format: {url}")

    async def scrape_profile(self, url: str) -> ScrapedProfile:
        """Scrape a single Stripe profile page"""
        username, profile_code = self.parse_url(url)

        if not self.browser:
            await self.start()

        page = await self.browser.new_page()

        try:
            # Set realistic headers
            await page.set_extra_http_headers({
                'Accept-Language': 'en-US,en;q=0.9',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            })

            logger.info(f"Navigating to {url}")

            # Navigate and wait for network to be idle
            await page.goto(url, wait_until='networkidle', timeout=30000)

            # Wait for content to load (Stripe likely uses React/Next.js)
            await page.wait_for_timeout(2000)

            # Try to wait for specific elements
            try:
                await page.wait_for_selector('[data-testid], .profile-content, main, article', timeout=5000)
            except:
                pass

            # Get page content
            html_content = await page.content()

            # Parse with BeautifulSoup
            soup = BeautifulSoup(html_content, 'lxml')

            # Extract data from page
            data = await self._extract_data(page, soup)

            return ScrapedProfile(
                username=username,
                profile_code=profile_code,
                full_url=url,
                display_name=data.get('display_name'),
                business_name=data.get('business_name'),
                description=data.get('description'),
                website_url=data.get('website_url'),
                logo_url=data.get('logo_url'),
                country=data.get('country'),
                industry=data.get('industry'),
                business_type=data.get('business_type'),
                metrics=data.get('metrics'),
                all_data=data,
                raw_html=html_content
            )

        except Exception as e:
            logger.error(f"Error scraping {url}: {str(e)}")
            raise
        finally:
            await page.close()

    async def _extract_data(self, page: Page, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract all available data from the profile page"""
        data = {}

        # Try to get data from JavaScript state (React/Next.js apps often have this)
        try:
            js_data = await page.evaluate('''() => {
                // Look for Next.js data
                if (window.__NEXT_DATA__) {
                    return { source: 'next', data: window.__NEXT_DATA__ };
                }
                // Look for React props
                const rootEl = document.getElementById('__next') || document.getElementById('root') || document.getElementById('app');
                if (rootEl && rootEl._reactRootContainer) {
                    return { source: 'react', data: 'React root found' };
                }
                // Look for any global state
                if (window.__INITIAL_STATE__) {
                    return { source: 'initial_state', data: window.__INITIAL_STATE__ };
                }
                if (window.__APP_STATE__) {
                    return { source: 'app_state', data: window.__APP_STATE__ };
                }
                return null;
            }''')
            if js_data:
                data['js_state'] = js_data
                logger.info(f"Found JS state: {js_data.get('source')}")
        except Exception as e:
            logger.warning(f"Could not extract JS state: {e}")

        # Extract from script tags (often contains JSON data)
        for script in soup.find_all('script', type='application/json'):
            try:
                script_data = json.loads(script.string)
                data['script_json'] = script_data
            except:
                pass

        for script in soup.find_all('script', id=re.compile(r'__NEXT_DATA__|__NUXT__|__INITIAL')):
            try:
                script_data = json.loads(script.string)
                data['framework_data'] = script_data
            except:
                pass

        # Extract meta tags
        meta_data = {}
        for meta in soup.find_all('meta'):
            name = meta.get('name') or meta.get('property', '')
            content = meta.get('content', '')
            if name and content:
                meta_data[name] = content
        data['meta_tags'] = meta_data

        # Common extraction patterns
        # Title
        if soup.title:
            data['page_title'] = soup.title.string

        # OG tags (often have business info)
        data['display_name'] = meta_data.get('og:title') or meta_data.get('twitter:title')
        data['description'] = meta_data.get('og:description') or meta_data.get('description')
        data['logo_url'] = meta_data.get('og:image') or meta_data.get('twitter:image')
        data['website_url'] = meta_data.get('og:url')

        # Try common selectors for profile pages
        selectors_to_try = {
            'display_name': ['h1', '[data-testid="display-name"]', '.profile-name', '.business-name'],
            'description': ['[data-testid="description"]', '.profile-description', '.business-description', 'p.description'],
            'website': ['a[href*="http"]:not([href*="stripe.com"])', '[data-testid="website"]'],
            'country': ['[data-testid="country"]', '.country', '.location'],
            'industry': ['[data-testid="industry"]', '.industry', '.business-type'],
        }

        for field, selectors in selectors_to_try.items():
            if not data.get(field):
                for selector in selectors:
                    try:
                        element = soup.select_one(selector)
                        if element:
                            if field == 'website' and element.name == 'a':
                                data['website_url'] = element.get('href')
                            else:
                                data[field] = element.get_text(strip=True)
                            break
                    except:
                        pass

        # Extract all text content as fallback
        main_content = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile(r'content|main|profile'))
        if main_content:
            data['main_text'] = main_content.get_text(separator='\n', strip=True)[:5000]

        # Try to find metrics/charts data
        metrics = {}
        # Look for chart containers
        chart_elements = soup.find_all(['canvas', 'svg', '[data-highcharts-chart]', '[class*="chart"]'])
        if chart_elements:
            metrics['charts_found'] = len(chart_elements)

        # Look for data tables
        tables = soup.find_all('table')
        for i, table in enumerate(tables):
            headers = [th.get_text(strip=True) for th in table.find_all('th')]
            rows = []
            for tr in table.find_all('tr'):
                row = [td.get_text(strip=True) for td in tr.find_all(['td', 'th'])]
                if row:
                    rows.append(row)
            if rows:
                metrics[f'table_{i}'] = {'headers': headers, 'rows': rows}

        if metrics:
            data['metrics'] = metrics

        # Extract all links
        links = []
        for a in soup.find_all('a', href=True):
            href = a.get('href')
            text = a.get_text(strip=True)
            if href and not href.startswith('#'):
                links.append({'href': href, 'text': text})
        data['links'] = links[:50]  # Limit to 50 links

        # Extract images
        images = []
        for img in soup.find_all('img', src=True):
            src = img.get('src')
            alt = img.get('alt', '')
            if src:
                images.append({'src': src, 'alt': alt})
        data['images'] = images[:20]  # Limit to 20 images

        return data


# Global scraper instance
scraper = StripeProfileScraper()


async def get_scraper() -> StripeProfileScraper:
    if not scraper.browser:
        await scraper.start()
    return scraper
