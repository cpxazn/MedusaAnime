# coding=utf-8
"""LiveChart.me anime client."""
from __future__ import unicode_literals

import logging
import re
from datetime import datetime
from typing import List, Optional

from bs4 import BeautifulSoup

from medusa import app
from medusa.clients.anime import AnimeSeries, AnimeSeason, AnimeSource
from medusa.logger.adapters.style import BraceAdapter
from medusa.session.core import MedusaSession


log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class LiveChartClient(AnimeSource):
    """Client for scraping anime data from livechart.me."""

    BASE_URL = 'https://www.livechart.me'
    SEARCH_URL = f'{BASE_URL}/search?q={{query}}'
    ANIME_URL = f'{BASE_URL}/anime/{{anime_id}}'
    SEASONAL_URL = f'{BASE_URL}/upcoming'
    RATE_LIMIT = 5  # requests per second

    def __init__(self):
        """Initialize the LiveChart client."""
        self.session = MedusaSession()
        self.session.update_headers({
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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
            log.warning('LiveChart request failed for {url}: {error!r}', url=url, error=error)
            return None

    def search(self, query: str) -> List[AnimeSeries]:
        """Search for anime by title.
        
        Args:
            query: Search query string
            
        Returns:
            List of matching AnimeSeries objects
        """
        results = []
        
        # Build search URL - livechart.me uses /search?q=query
        search_url = self.SEARCH_URL.format(query=query)
        soup = self._get(search_url)
        
        if not soup:
            return results

        # Parse search results from livechart.me
        # Search results are typically in a list or grid
        anime_cards = soup.find_all('a', class_=re.compile(r'anime-card|anime-link|series-link', re.I))
        
        for card in anime_cards[:20]:  # Limit results
            anime = self._parse_anime_from_card(card)
            if anime:
                results.append(anime)

        # Also try searching within the upcoming list
        if not results:
            upcoming_soup = self._get(self.SEASONAL_URL)
            if upcoming_soup:
                results.extend(self._parse_anime_list(upcoming_soup))

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
        
        # LiveChart.me doesn't have direct seasonal URLs
        # Use upcoming page and filter by season/year
        soup = self._get(self.SEASONAL_URL)
        
        if soup:
            results = self._parse_anime_list(soup, year, season)

        return results

    def get_details(self, anime_id: int) -> AnimeSeries:
        """Get detailed information for a specific anime.
        
        Args:
            anime_id: LiveChart anime ID
            
        Returns:
            AnimeSeries object with full details
        """
        anime_url = self.ANIME_URL.format(anime_id=anime_id)
        soup = self._get(anime_url)
        
        if not soup:
            return AnimeSeries(anime_id=anime_id, source='livechart')

        return self._parse_anime_details(soup, anime_id)

    def get_upcoming(self, limit: int = 20) -> List[AnimeSeries]:
        """Get upcoming anime releases.
        
        Args:
            limit: Maximum number of results to return
            
        Returns:
            List of upcoming AnimeSeries objects
        """
        soup = self._get(self.SEASONAL_URL)
        
        if not soup:
            return []

        return self._parse_anime_list(soup, limit=limit)

    def _parse_anime_from_card(self, card) -> Optional[AnimeSeries]:
        """Parse anime data from a search result card.
        
        Args:
            card: BeautifulSoup element representing an anime card
            
        Returns:
            AnimeSeries object or None
        """
        try:
            # Get the link to the anime page
            link = card.find('a', href=True)
            if not link:
                return None

            href = link['href']
            # Extract anime ID from URL
            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                return None

            anime_id = int(anime_id_match.group(1))
            
            # Get title
            title_elem = link.find(['h3', 'h4', 'span', 'div'], class_=re.compile(r'title|name', re.I))
            if not title_elem:
                title_elem = link.find(['h3', 'h4', 'span'])
            
            title = title_elem.get_text(strip=True) if title_elem else None

            # Get image
            img = link.find('img')
            image_url = img.get('src') or img.get('data-src') if img else None

            # Build full URL
            url = f"{self.BASE_URL}{href}" if href.startswith('/') else href

            return AnimeSeries(
                anime_id=anime_id,
                source='livechart',
                title_romanji=title,
                image_url=image_url,
                url=url,
            )
        except Exception as error:
            log.debug('Failed to parse anime card: {error}', error=error)
            return None

    def _parse_anime_list(self, soup: BeautifulSoup, year: Optional[int] = None, 
                          season: Optional[str] = None, limit: Optional[int] = None) -> List[AnimeSeries]:
        """Parse a list of anime from HTML.
        
        Args:
            soup: Parsed HTML
            year: Optional year filter
            season: Optional season filter
            limit: Optional result limit
            
        Returns:
            List of AnimeSeries objects
        """
        results = []
        
        # Find anime entries - livechart.me uses various classes
        anime_entries = soup.find_all(['article', 'div'], class_=re.compile(r'anime|series|card', re.I))
        
        if not anime_entries:
            # Try alternative selectors
            anime_entries = soup.find_all('a', href=re.compile(r'/anime/\d+'))

        for entry in anime_entries:
            if limit and len(results) >= limit:
                break

            anime = self._parse_anime_from_card(entry)
            if not anime:
                # Try parsing as a link
                link = entry.find('a', href=True) if hasattr(entry, 'find') else None
                if link:
                    anime = self._parse_anime_from_card(link)
            
            if anime:
                # Apply filters
                if year and anime.year and anime.year != year:
                    continue
                if season and anime.season and anime.season.upper() != season.upper():
                    continue
                
                results.append(anime)

        return results

    def _parse_anime_details(self, soup: BeautifulSoup, anime_id: int) -> AnimeSeries:
        """Parse detailed anime information from the anime page.
        
        Args:
            soup: Parsed HTML of the anime page
            anime_id: LiveChart anime ID
            
        Returns:
            AnimeSeries object with full details
        """
        anime = AnimeSeries(anime_id=anime_id, source='livechart')

        try:
            # Get the main anime title section
            title_section = soup.find('section', id=re.compile(r'anime-title', re.I))
            if not title_section:
                # Try alternative selectors
                title_section = soup.find('section') or soup

            # Japanese title
            jp_title = title_section.find(string=re.compile(r'[\u4e00-\u9fff\u3040-\u30ff]', re.U))
            if jp_title:
                anime.title_japanese = jp_title.strip()

            # Romanji title
            romanji_elem = title_section.find(class_=re.compile(r'romanji|title-romanji', re.I))
            if romanji_elem:
                anime.title_romanji = romanji_elem.get_text(strip=True)
            
            # English title
            english_elem = title_section.find(class_=re.compile(r'english|title-english', re.I))
            if english_elem:
                anime.title_english = english_elem.get_text(strip=True)

            # Synonyms
            synonym_elem = title_section.find(class_=re.compile(r'synonym', re.I))
            if synonym_elem:
                syns = synonym_elem.get_text(strip=True)
                anime.title_synonyms = [s.strip() for s in syns.split(',') if s.strip()]

            # Synopsis/Description
            desc_section = soup.find('section', id=re.compile(r'anime-description|synopsis', re.I))
            if not desc_section:
                desc_section = soup.find('section', class_=re.compile(r'description|synopsis', re.I))
            if desc_section:
                anime.synopsis = desc_section.get_text(strip=True)

            # Get anime metadata from the info section
            info_section = soup.find('section', id=re.compile(r'anime-info', re.I))
            if not info_section:
                info_section = soup.find('section', class_=re.compile(r'info', re.I))
            
            if info_section:
                anime = self._parse_anime_info(info_section, anime)

            # Get image
            img_section = soup.find('section', id=re.compile(r'anime-image', re.I))
            if img_section:
                img = img_section.find('img')
                if img:
                    anime.image_url = img.get('src') or img.get('data-src')

            # Get URL
            anime.url = f"{self.BASE_URL}/anime/{anime_id}"

        except Exception as error:
            log.debug('Failed to parse anime details for ID {anime_id}: {error}', anime_id=anime_id, error=error)

        return anime

    def _parse_anime_info(self, info_section, anime: AnimeSeries) -> AnimeSeries:
        """Parse anime metadata from info section.
        
        Args:
            info_section: BeautifulSoup element with anime info
            anime: AnimeSeries to update
            
        Returns:
            Updated AnimeSeries
        """
        try:
            # Find all info rows (typically <li> or <div> elements)
            info_items = info_section.find_all(['li', 'div', 'tr'], class_=re.compile(r'media|type|status|date|episode', re.I))
            
            for item in info_items:
                text = item.get_text(strip=True).lower()
                
                # Anime type (TV, Movie, OVA, etc.)
                if 'media' in text or 'type' in text:
                    media_type = self._extract_value(item)
                    if media_type:
                        anime.anime_type = media_type.upper()
                
                # Status (airing, finished, etc.)
                if 'status' in text:
                    status = self._extract_value(item)
                    if status:
                        anime.status = status.lower()
                
                # Episodes
                if 'episode' in text:
                    ep_text = self._extract_value(item)
                    if ep_text:
                        try:
                            anime.episodes = int(re.search(r'\d+', ep_text).group())
                        except (AttributeError, ValueError):
                            pass

            # Find date information
            date_items = info_section.find_all(['li', 'div', 'tr'], class_=re.compile(r'start|end|aired|date', re.I))
            for item in date_items:
                text = item.get_text(strip=True)
                date_match = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', text)
                if date_match:
                    date_str = date_match.group(0)
                    try:
                        parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                        if 'end' in text.lower() or 'ended' in text.lower():
                            anime.end_date = date_str
                        else:
                            anime.start_date = date_str
                            anime.year = parsed_date.year
                            anime.season = self._month_to_season(parsed_date.month)
                    except ValueError:
                        pass

            # Try to extract season/year from text patterns
            season_match = re.search(r'(Spring|Summer|Fall|Autumn|Winter)\s+(\d{4})', info_section.get_text())
            if season_match:
                season_map = {'Spring': 'SPRING', 'Summer': 'SUMMER', 'Fall': 'FALL', 'Autumn': 'FALL'}
                anime.season = season_map.get(season_match.group(1), anime.season)
                anime.year = int(season_match.group(2))

            # Genres
            genre_section = info_section.find('section', id=re.compile(r'anime-genre', re.I)) if hasattr(info_section, 'find') else None
            if not genre_section:
                genre_section = info_section.find(class_=re.compile(r'genre', re.I)) if hasattr(info_section, 'find') else None
            
            if genre_section:
                genre_links = genre_section.find_all('a', href=re.compile(r'/genre/'))
                anime.genres = [link.get_text(strip=True) for link in genre_links]

        except Exception as error:
            log.debug('Failed to parse anime info: {error}', error=error)

        return anime

    def _extract_value(self, element) -> str:
        """Extract value text from an info item.
        
        Args:
            element: BeautifulSoup element
            
        Returns:
            Value string or None
        """
        try:
            # Value is typically in the last <span> or after the label
            spans = element.find_all('span')
            if len(spans) >= 2:
                return spans[-1].get_text(strip=True)
            return element.get_text(strip=True)
        except Exception:
            return element.get_text(strip=True) if hasattr(element, 'get_text') else ''

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
