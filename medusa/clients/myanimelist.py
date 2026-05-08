# coding=utf-8
"""MyAnimeList.net anime client (scraping-based)."""
from __future__ import unicode_literals

import logging
import re
from typing import List, Optional

from bs4 import BeautifulSoup

from medusa import app
from medusa.clients.anime import AnimeSeries, AnimeSeason, AnimeSource
from medusa.logger.adapters.style import BraceAdapter
from medusa.session.core import MedusaSession


log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class MyAnimeListClient(AnimeSource):
    """Client for scraping anime data from myanimelist.net.
    
    This client uses HTML scraping to work without API access.
    Once API access is approved, the scraping logic can be replaced
    with API calls while maintaining the same interface.
    """

    BASE_URL = 'https://myanimelist.net'
    SEARCH_URL = f'{BASE_URL}/anime.php?q={{query}}'
    ANIME_URL = f'{BASE_URL}/anime/{{anime_id}}'
    SEASONAL_URL = f'{BASE_URL}/anime/season/{{year}}/{{season}}'
    RATE_LIMIT = 10  # requests per second (unauthenticated)

    # Season mapping
    SEASON_MAP = {
        'spring': 'SPRING',
        'summer': 'SUMMER',
        'fall': 'FALL',
        'autumn': 'FALL',
        'winter': 'WINTER',
    }

    def __init__(self):
        """Initialize the MyAnimeList client."""
        self.session = MedusaSession()
        self.session.headers.update({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
            'User-Agent': 'Medusa Anime Lookup (contact: medusa-project)',
        })

    def _get(self, url: str) -> Optional[BeautifulSoup]:
        """Make a GET request and return parsed HTML.
        
        Args:
            url: URL to fetch
            
        Returns:
            Parsed BeautifulSoup object or None on error
        """
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return BeautifulSoup(response.text, 'html.parser')
        except Exception as error:
            log.warning('MyAnimeList request failed for {url}: {error!r}', url=url, error=error)
            return None

    def search(self, query: str) -> List[AnimeSeries]:
        """Search for anime by title.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching AnimeSeries objects
        """
        results = []
        
        # Build search URL - MAL uses /anime.php?q=query
        search_url = self.SEARCH_URL.format(query=query)
        soup = self._get(search_url)
        
        if not soup:
            return results

        # Parse search results from MAL
        # MAL search results are in a table with class 'js-categories-seasonal' or similar
        anime_items = soup.find_all('div', class_='js-categories-seasonal')
        
        if not anime_items:
            # Try alternative selectors for search results
            anime_items = soup.find_all('div', class_='information')
        
        for item in anime_items[:20]:  # Limit results
            anime = self._parse_search_result(item)
            if anime:
                results.append(anime)

        return results

    def get_seasonal(self, year: int, season: str) -> List[AnimeSeries]:
        """Get seasonal anime for a given year/season.
        
        Args:
            year: Year (e.g., 2026)
            season: Season (SPRING, SUMMER, FALL, WINTER)
            
        Returns:
            List of AnimeSeries for the season
        """
        results = []
        
        # Build seasonal URL
        season_lower = season.lower() if season else 'spring'
        seasonal_url = self.SEASONAL_URL.format(year=year, season=season_lower)
        soup = self._get(seasonal_url)
        
        if soup:
            results = self._parse_seasonal_page(soup, year, season)

        return results

    def get_details(self, mal_id: int) -> AnimeSeries:
        """Get detailed information for a specific anime.
        
        Args:
            mal_id: MyAnimeList anime ID
            
        Returns:
            AnimeSeries object with full details
        """
        anime_url = self.ANIME_URL.format(anime_id=mal_id)
        soup = self._get(anime_url)
        
        if not soup:
            return AnimeSeries(anime_id=mal_id, source='myanimelist')

        return self._parse_anime_details(soup, mal_id)

    def get_upcoming(self, limit: int = 20) -> List[AnimeSeries]:
        """Get upcoming anime releases.
        
        Args:
            limit: Maximum number of results to return
            
        Returns:
            List of upcoming AnimeSeries objects
        """
        # Get current season's upcoming anime
        from datetime import datetime
        now = datetime.now()
        season = self._month_to_season(now.month)
        year = now.year
        
        # Try current year first, then next year if needed
        results = self.get_seasonal(year, season)
        
        if len(results) < limit:
            # If we need more, try next season
            next_season = self._next_season(season)
            next_year = year if season != 'WINTER' else year + 1
            next_results = self.get_seasonal(next_year, next_season)
            results.extend(next_results[:limit - len(results)])
        
        return results[:limit]

    def _parse_search_result(self, item) -> Optional[AnimeSeries]:
        """Parse anime data from a search result item.
        
        Args:
            item: BeautifulSoup element representing a search result
            
        Returns:
            AnimeSeries object or None
        """
        try:
            # Get the link to the anime page
            link = item.find('a', class_='hoverinfo-trigger')
            if not link:
                # Try alternative selector
                link = item.find('a', href=re.compile(r'/anime/'))
            
            if not link:
                return None

            href = link.get('href', '')
            # Extract anime ID from URL
            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                return None

            anime_id = int(anime_id_match.group(1))
            
            # Get title from the link
            title = link.get_text(strip=True)

            # Get more details from the item
            title_elem = item.find('h3') or item.find(class_='title')
            if title_elem:
                title_links = title_elem.find_all('a')
                if title_links:
                    title = title_links[0].get_text(strip=True)

            # Get synopsis
            desc_elem = item.find('p', class_='preformatted') or item.find('div', class_='sentence')
            synopsis = desc_elem.get_text(strip=True) if desc_elem else None

            # Get additional info (episodes, score, etc.)
            info_elem = item.find('div', class_='information') or item.find('td', class_='borderClass')
            
            # Get image
            img = item.find('img')
            image_url = img.get('src') or img.get('data-src') if img else None

            # Build display URL
            url = f"{self.BASE_URL}{href}" if href.startswith('/') else href

            # Try to extract year from title or other elements
            year = None
            year_match = re.search(r'(\d{4})', title)
            if year_match:
                year = int(year_match.group(1))

            return AnimeSeries(
                anime_id=anime_id,
                source='myanimelist',
                mal_id=anime_id,
                title_english=title,
                synopsis=synopsis,
                image_url=image_url,
                url=url,
                year=year,
            )
        except Exception as error:
            log.debug('Failed to parse search result: {error}', error=error)
            return None

    def _parse_seasonal_page(self, soup: BeautifulSoup, year: int, season: str) -> List[AnimeSeries]:
        """Parse seasonal anime from the seasonal page.
        
        Args:
            soup: Parsed HTML of the seasonal page
            year: Year of the season
            season: Season string
            
        Returns:
            List of AnimeSeries objects
        """
        results = []
        
        # MAL seasonal page has a table structure
        # Look for anime entries in the seasonal table
        anime_rows = soup.find_all('tr', class_=re.compile(r'anime-planning|anime-list-', re.I))
        
        if not anime_rows:
            # Try alternative: look for all anime entries in the seasonal section
            seasonal_section = soup.find('table', class_=re.compile(r'seasonal', re.I))
            if seasonal_section:
                anime_rows = seasonal_section.find_all('tr')
            else:
                # Fallback: find all anime links in the page
                anime_links = soup.find_all('a', href=re.compile(r'/anime/\d+'))
                for link in anime_links[:50]:
                    anime = self._parse_anime_link(link, year, season)
                    if anime:
                        results.append(anime)
                return results

        for row in anime_rows:
            anime = self._parse_seasonal_row(row, year, season)
            if anime:
                results.append(anime)

        return results

    def _parse_anime_link(self, link, year: int, season: str) -> Optional[AnimeSeries]:
        """Parse anime data from a link element.
        
        Args:
            link: BeautifulSoup <a> element
            year: Year to set
            season: Season to set
            
        Returns:
            AnimeSeries object or None
        """
        try:
            href = link.get('href', '')
            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                return None

            anime_id = int(anime_id_match.group(1))
            title = link.get_text(strip=True)
            url = f"{self.BASE_URL}{href}" if href.startswith('/') else href

            return AnimeSeries(
                anime_id=anime_id,
                source='myanimelist',
                mal_id=anime_id,
                title_english=title,
                url=url,
                year=year,
                season=season,
            )
        except Exception as error:
            log.debug('Failed to parse anime link: {error}', error=error)
            return None

    def _parse_seasonal_row(self, row, year: int, season: str) -> Optional[AnimeSeries]:
        """Parse anime data from a seasonal row.
        
        Args:
            row: BeautifulSoup <tr> element
            year: Year to set
            season: Season to set
            
        Returns:
            AnimeSeries object or None
        """
        try:
            # Get the anime link
            link = row.find('a', href=re.compile(r'/anime/'))
            if not link:
                return None

            href = link.get('href', '')
            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                return None

            anime_id = int(anime_id_match.group(1))
            
            # Get title
            title_elem = link.find('strong') or link
            title = title_elem.get_text(strip=True)

            # Get additional info from the row
            info_cells = row.find_all('td')
            
            # Parse episodes, score, members from cells
            episodes = None
            score = None
            members = None
            
            for cell in info_cells:
                cell_text = cell.get_text(strip=True)
                # Try to extract episodes
                ep_match = re.search(r'(\d+)\s*ep', cell_text)
                if ep_match:
                    episodes = int(ep_match.group(1))
                
                # Try to extract score (0-10)
                score_match = re.search(r'([\d.]+)\s*pts', cell_text)
                if score_match:
                    score = float(score_match.group(1))

            # Get image
            img = row.find('img')
            image_url = img.get('src') if img else None

            url = f"{self.BASE_URL}{href}" if href.startswith('/') else href

            return AnimeSeries(
                anime_id=anime_id,
                source='myanimelist',
                mal_id=anime_id,
                title_english=title,
                episodes=episodes,
                score=score,
                image_url=image_url,
                url=url,
                year=year,
                season=season,
            )
        except Exception as error:
            log.debug('Failed to parse seasonal row: {error}', error=error)
            return None

    def _parse_anime_details(self, soup: BeautifulSoup, mal_id: int) -> AnimeSeries:
        """Parse detailed anime information from the anime page.
        
        Args:
            soup: Parsed HTML of the anime page
            mal_id: MyAnimeList anime ID
            
        Returns:
            AnimeSeries object with full details
        """
        anime = AnimeSeries(anime_id=mal_id, source='myanimelist', mal_id=mal_id)

        try:
            # Get the main title
            title_section = soup.find('section', class_='header-title')
            if not title_section:
                title_section = soup.find('h1', class_=re.compile(r'se-title', re.I))
            
            if title_section:
                title_elem = title_section.find('span', class_='')
                if title_elem:
                    anime.title_english = title_elem.get_text(strip=True)
                else:
                    anime.title_english = title_section.get_text(strip=True)

            # Get alternative titles
            title_alt = soup.find('div', class_='title-alt')
            if title_alt:
                jp_text = title_alt.find('span', class_='')
                if jp_text:
                    text = jp_text.get_text(strip=True)
                    if '\u4e00' in text or '\u3040' in text:
                        anime.title_japanese = text
                    else:
                        anime.title_romanji = text

            # Get synonyms from the title alternatives section
            syn_section = soup.find('span', class_='title-name')
            if syn_section:
                parent = syn_section.find_parent()
                if parent:
                    syn_text = parent.get_text()
                    if ':' in syn_text:
                        parts = syn_text.split(':', 1)
                        if len(parts) > 1:
                            anime.title_synonyms = [s.strip() for s in parts[1].split(',') if s.strip()]

            # Get synopsis
            synopsis_section = soup.find('p', class_='') or soup.find('div', class_='')
            if synopsis_section:
                # Look for the synopsis paragraph
                for p in soup.find_all('p'):
                    if 'synopsis' in p.get('data-text', '') or 'story' in p.get('data-text', ''):
                        anime.synopsis = p.get_text(strip=True)
                        break
                
                # Fallback: look for common synopsis patterns
                if not anime.synopsis:
                    for p in soup.find_all('p'):
                        text = p.get_text(strip=True)
                        if len(text) > 100 and 'episode' not in text.lower():
                            anime.synopsis = text
                            break

            # Get image
            image_section = soup.find('img', class_=re.compile(r'lazyload|lazyload', re.I))
            if image_section:
                anime.image_url = image_section.get('data-src') or image_section.get('src')
            
            # Fallback for image
            if not anime.image_url:
                image_section = soup.find('div', class_='big-image') or soup.find('div', class_='admin-image')
                if image_section:
                    img = image_section.find('img')
                    if img:
                        anime.image_url = img.get('src') or img.get('data-src')

            # Get anime metadata from the info table
            info_table = soup.find('table', class_='statistics') or soup.find('table', class_='statistics-table')
            if info_table:
                anime = self._parse_info_table(info_table, anime)

            # Get genres and tags
            genre_tags = soup.find_all('a', class_=re.compile(r'tag', re.I))
            for tag in genre_tags:
                tag_text = tag.get_text(strip=True)
                if 'genre' in tag.get('href', ''):
                    anime.genres.append(tag_text)
                elif 'tag' in tag.get('href', ''):
                    anime.tags.append(tag_text)

            # Get URL
            anime.url = f"{self.BASE_URL}/anime/{mal_id}"

            # Look for cross-references (AniDB, AniList IDs)
            links_section = soup.find('table', class_='statistics-table')
            if links_section:
                for link in links_section.find_all('a'):
                    href = link.get('href', '').replace('&amp;', '&')
                    if 'anidb.net' in href:
                        anidb_match = re.search(r'aid=(\d+)', href)
                        if anidb_match:
                            anime.anidb_id = int(anidb_match.group(1))
                    if 'anilist.co' in href:
                        anilist_match = re.search(r'/anime/(\d+)', href)
                        if anilist_match:
                            anime.anilist_id = int(anilist_match.group(1))

            if not anime.anidb_id or not anime.anilist_id:
                for link in soup.find_all('a', href=True):
                    href = (link.get('href') or '').replace('&amp;', '&')
                    if not href:
                        continue

                    if 'anidb.net' in href and not anime.anidb_id:
                        anidb_match = re.search(r'aid=(\d+)', href)
                        if anidb_match:
                            anime.anidb_id = int(anidb_match.group(1))

                    if 'anilist.co' in href and not anime.anilist_id:
                        anilist_match = re.search(r'/anime/(\d+)', href)
                        if anilist_match:
                            anime.anilist_id = int(anilist_match.group(1))

        except Exception as error:
            log.debug('Failed to parse anime details for MAL ID {mal_id}: {error}', mal_id=mal_id, error=error)

        return anime

    def _parse_info_table(self, table, anime: AnimeSeries) -> AnimeSeries:
        """Parse anime info table.
        
        Args:
            table: BeautifulSoup <table> element
            anime: AnimeSeries to update
            
        Returns:
            Updated AnimeSeries
        """
        try:
            rows = table.find_all('tr')
            for row in rows:
                labels = row.find_all(['th', 'td'], class_=re.compile(r'title|name', re.I))
                values = row.find_all(['td', 'th'], class_=re.compile(r'value|data', re.I))
                
                if not labels and not values:
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True).lower()
                        value = cells[1].get_text(strip=True)
                    else:
                        continue
                else:
                    label = labels[0].get_text(strip=True).lower() if labels else ''
                    value = values[0].get_text(strip=True) if values else ''

                # Type (TV, Movie, OVA, etc.)
                if 'type' in label:
                    anime.anime_type = value.upper()
                
                # Status (Currently Airing, Finished, etc.)
                elif 'status' in label:
                    status_map = {
                        'currently airing': 'airing',
                        'finished': 'finished',
                        'not yet aired': 'upcoming',
                    }
                    anime.status = status_map.get(value.lower(), value.lower())
                
                # Episodes
                elif 'episodes' in label:
                    if value == '?':
                        anime.episodes = None
                    else:
                        try:
                            anime.episodes = int(re.search(r'\d+', value).group())
                        except (AttributeError, ValueError):
                            pass
                
                # Score/Rating
                elif 'score' in label:
                    score_match = re.search(r'([\d.]+)', value)
                    if score_match:
                        anime.score = float(score_match.group(1))
                
                # Aired dates
                elif 'aired' in label or 'date' in label:
                    date_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', value)
                    if date_match:
                        anime.year = int(date_match.group(1))
                        anime.season = self._month_to_season(int(date_match.group(2)))

        except Exception as error:
            log.debug('Failed to parse info table: {error}', error=error)

        return anime

    def _month_to_season(self, month: int) -> str:
        """Convert month number to season.
        
        Args:
            month: Month number (1-12)
            
        Returns:
            Season string (SPRING, SUMMER, FALL, WINTER)
        """
        if month in (12, 1, 2):
            return 'WINTER'
        elif month in (3, 4, 5):
            return 'SPRING'
        elif month in (6, 7, 8):
            return 'SUMMER'
        else:
            return 'FALL'

    def _next_season(self, current: str) -> str:
        """Get the next season after the current one.
        
        Args:
            current: Current season
            
        Returns:
            Next season
        """
        seasons = ['SPRING', 'SUMMER', 'FALL', 'WINTER']
        try:
            idx = seasons.index(current)
            return seasons[(idx + 1) % 4]
        except ValueError:
            return 'SPRING'
