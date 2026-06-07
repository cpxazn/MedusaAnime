# coding=utf-8
"""MyAnimeList anime client with official API support and scraper fallback."""
from __future__ import unicode_literals

import logging
import re
from typing import Any, Dict, List, Optional

from bs4 import BeautifulSoup

from medusa import app
from medusa.clients.anime import AnimeSeries, AnimeSeason, AnimeSource
from medusa.logger.adapters.style import BraceAdapter
from medusa.session.core import MedusaSession


log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class MyAnimeListClient(AnimeSource):
    """Client for anime data from MyAnimeList."""

    BASE_URL = 'https://myanimelist.net'
    SEARCH_URL = f'{BASE_URL}/anime.php?q={{query}}'
    ANIME_URL = f'{BASE_URL}/anime/{{anime_id}}'
    SEASONAL_URL = f'{BASE_URL}/anime/season/{{year}}/{{season}}'
    API_BASE_URL = 'https://api.myanimelist.net/v2'
    TOKEN_URL = 'https://myanimelist.net/v1/oauth2/token'
    RATE_LIMIT = 10  # requests per second (unauthenticated)
    API_PAGE_SIZE = 100
    API_SEASONAL_FIELDS = (
        'id,title,main_picture,alternative_titles,start_date,synopsis,mean,num_list_users,media_type,status,genres,'
        'num_episodes,start_season,average_episode_duration,studios'
    )
    API_DETAILS_FIELDS = (
        'id,title,main_picture,alternative_titles,start_date,end_date,synopsis,mean,rank,popularity,'
        'num_list_users,num_scoring_users,nsfw,created_at,updated_at,media_type,status,genres,'
        'my_list_status,num_episodes,start_season,broadcast,source,average_episode_duration,rating,'
        'pictures,background,related_anime,related_manga,recommendations,studios,statistics'
    )

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
        self.use_official_api = bool(app.USE_MAL_API and app.MAL_ACCESS_TOKEN)

    @classmethod
    def _token_payload(cls, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Post to the MAL token endpoint and return parsed token data."""
        session = MedusaSession()
        try:
            response = session.post(cls.TOKEN_URL, data=payload, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as error:
            log.warning('MyAnimeList token request failed: {error!r}', error=error)
            return None

    @classmethod
    def apply_token_data(cls, token_data: Dict[str, Any]) -> bool:
        """Persist access and refresh tokens in runtime config."""
        access_token = token_data.get('access_token')
        refresh_token = token_data.get('refresh_token') or app.MAL_REFRESH_TOKEN
        if not access_token:
            return False

        app.MAL_ACCESS_TOKEN = access_token
        app.MAL_REFRESH_TOKEN = refresh_token
        app.USE_MAL_API = True

        if app.instance:
            app.instance.save_config()

        return True

    @classmethod
    def exchange_authorization_code(cls, code: str, code_verifier: str, redirect_uri: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Exchange an OAuth authorization code for MAL tokens."""
        payload = {
            'grant_type': 'authorization_code',
            'client_id': app.MAL_CLIENT_ID,
            'code': code,
            'code_verifier': code_verifier,
        }
        if app.MAL_CLIENT_SECRET:
            payload['client_secret'] = app.MAL_CLIENT_SECRET
        if redirect_uri:
            payload['redirect_uri'] = redirect_uri

        return cls._token_payload(payload)

    def _api_headers(self) -> Dict[str, str]:
        """Build headers for official MAL API requests."""
        return {
            'Authorization': 'Bearer {token}'.format(token=app.MAL_ACCESS_TOKEN),
            'Accept': 'application/json',
            'User-Agent': 'Medusa Anime Lookup (contact: medusa-project)',
        }

    def _api_get(self, url: str, params: Optional[Dict[str, Any]] = None, retry: bool = True) -> Optional[Dict[str, Any]]:
        """Make a GET request against the official MAL API."""
        if not self.use_official_api:
            return None

        try:
            response = self.session.get(url, params=params, headers=self._api_headers(), timeout=30)
            if response.status_code == 401 and retry and self._refresh_access_token():
                return self._api_get(url, params=params, retry=False)

            response.raise_for_status()
            return response.json()
        except Exception as error:
            log.warning('MyAnimeList API request failed for {url}: {error!r}', url=url, error=error)
            return None

    def _refresh_access_token(self) -> bool:
        """Refresh the MAL access token when a refresh token is configured."""
        if not (app.MAL_CLIENT_ID and app.MAL_REFRESH_TOKEN):
            return False

        payload = {
            'grant_type': 'refresh_token',
            'refresh_token': app.MAL_REFRESH_TOKEN,
            'client_id': app.MAL_CLIENT_ID,
        }
        if app.MAL_CLIENT_SECRET:
            payload['client_secret'] = app.MAL_CLIENT_SECRET

        token_data = self._token_payload(payload)
        if token_data is None:
            log.warning('MyAnimeList token refresh failed')
            return False

        if not self.apply_token_data(token_data):
            return False

        self.use_official_api = True
        return True

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

        # MAL search pages contain many /anime/<id> links per result card
        # (title link, image link, read more, etc.). Build one result per anime id.
        links = soup.find_all('a', href=re.compile(r'/anime/\d+'))
        anime_map = {}

        for link in links:
            href = link.get('href', '')
            if not href or '/video' in href:
                continue

            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                continue

            anime_id = int(anime_id_match.group(1))
            entry = anime_map.setdefault(anime_id, {
                'href': href,
                'title': None,
                'image_url': None,
            })

            text = (link.get_text(' ', strip=True) or '').strip()
            classes = link.get('class') or []

            # Prefer explicit title links and ignore helper links like "read more.".
            if text and text.lower() != 'read more.':
                if entry['title'] is None or 'fw-b' in classes:
                    entry['title'] = text

            # Some entries store poster on the image anchor (text-less link).
            img = link.find('img')
            if not img and link.parent is not None:
                img = link.parent.find('img')
            if img and entry['image_url'] is None:
                entry['image_url'] = img.get('src') or img.get('data-src')

        for anime_id, entry in anime_map.items():
            title = entry['title']
            if not title:
                continue

            href = entry['href']
            url = href if href.startswith('http') else '{base}{href}'.format(base=self.BASE_URL, href=href)

            results.append(AnimeSeries(
                anime_id=anime_id,
                source='myanimelist',
                mal_id=anime_id,
                title_english=title,
                image_url=entry['image_url'],
                url=url,
            ))

            if len(results) >= 60:
                break

        return results

    def get_seasonal(self, year: int, season: str, source_sort: Optional[str] = None) -> List[AnimeSeries]:
        """Get seasonal anime for a given year/season.
        
        Args:
            year: Year (e.g., 2026)
            season: Season (SPRING, SUMMER, FALL, WINTER)
            source_sort: Optional MAL sort key, e.g. anime_num_list_users or anime_score
            
        Returns:
            List of AnimeSeries for the season
        """
        api_results = self._get_seasonal_api(year, season, source_sort=source_sort)
        if api_results is not None:
            return api_results

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
        api_anime = self._get_details_api(mal_id)
        if api_anime is not None:
            return api_anime

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

    def _get_seasonal_api(self, year: int, season: str, source_sort: Optional[str] = None) -> Optional[List[AnimeSeries]]:
        """Fetch seasonal anime from the official MAL API."""
        if not self.use_official_api:
            return None

        season_key = (season or 'SPRING').lower()
        sort_key = source_sort or 'anime_num_list_users'
        results = []
        offset = 0

        while True:
            payload = self._api_get(
                '{base}/anime/season/{year}/{season}'.format(base=self.API_BASE_URL, year=year, season=season_key),
                params={
                    'sort': sort_key,
                    'limit': self.API_PAGE_SIZE,
                    'offset': offset,
                    'fields': self.API_SEASONAL_FIELDS,
                }
            )
            if payload is None:
                return None if offset == 0 else results

            items = payload.get('data') or []
            if not items:
                break

            for item in items:
                anime = self._parse_api_anime(item.get('node', item))
                if anime:
                    results.append(anime)

            if len(items) < self.API_PAGE_SIZE:
                break
            offset += self.API_PAGE_SIZE

        return results

    def _get_details_api(self, mal_id: int) -> Optional[AnimeSeries]:
        """Fetch detailed anime metadata from the official MAL API."""
        if not self.use_official_api:
            return None

        payload = self._api_get(
            '{base}/anime/{anime_id}'.format(base=self.API_BASE_URL, anime_id=mal_id),
            params={'fields': self.API_DETAILS_FIELDS}
        )
        if payload is None:
            return None

        anime = self._parse_api_anime(payload, include_relations=True)
        if anime is None:
            return None

        return self._enrich_with_scraped_detail_page(anime, mal_id)

    def _parse_api_anime(self, data: Dict[str, Any], include_relations: bool = False) -> Optional[AnimeSeries]:
        """Map MAL API payloads onto the AnimeSeries model."""
        anime_id = data.get('id')
        if not anime_id:
            return None

        title = data.get('title')
        alt_titles = data.get('alternative_titles') or {}
        english_title = alt_titles.get('en') or title
        japanese_title = alt_titles.get('ja')
        synonyms = alt_titles.get('synonyms') or []

        anime = AnimeSeries(
            anime_id=anime_id,
            source='myanimelist',
            mal_id=anime_id,
            title_english=english_title,
            title_romanji=title,
            title_japanese=japanese_title,
            title_synonyms=[syn for syn in synonyms if syn],
            synopsis=data.get('synopsis'),
            start_date=data.get('start_date'),
            end_date=data.get('end_date'),
            episodes=data.get('num_episodes'),
            score=data.get('mean'),
            num_list_users=data.get('num_list_users'),
            url='{base}/anime/{anime_id}'.format(base=self.BASE_URL, anime_id=anime_id),
        )

        media_type = (data.get('media_type') or '').upper()
        if media_type:
            anime.anime_type = media_type

        status_map = {
            'currently_airing': 'airing',
            'finished_airing': 'finished',
            'not_yet_aired': 'upcoming',
        }
        anime.status = status_map.get(data.get('status'), anime.status)

        start_season = data.get('start_season') or {}
        anime.year = start_season.get('year')
        anime.season = (start_season.get('season') or '').upper() or None
        if anime.year is None and anime.start_date:
            year_match = re.match(r'(\d{4})-(\d{2})-(\d{2})', anime.start_date)
            if year_match:
                anime.year = int(year_match.group(1))
                anime.season = self._month_to_season(int(year_match.group(2)))

        duration = data.get('average_episode_duration')
        if duration:
            anime.episode_duration_minutes = int(duration / 60)

        anime.genres = [genre.get('name') for genre in data.get('genres') or [] if genre.get('name')]
        anime.studios = [studio.get('name') for studio in data.get('studios') or [] if studio.get('name')]

        main_picture = data.get('main_picture') or {}
        pictures = data.get('pictures') or []
        if main_picture:
            anime.image_url = main_picture.get('large') or main_picture.get('medium')
        if not anime.image_url and pictures:
            first_picture = pictures[0] or {}
            anime.image_url = first_picture.get('large') or first_picture.get('medium')

        # The official MAL API does not document AniDB IDs; preserve one if it appears unexpectedly.
        anime.anidb_id = data.get('anidb_id')
        anime.anilist_id = data.get('anilist_id')
        anime.tvdb_id = data.get('tvdb_id')

        if include_relations:
            for related in data.get('related_anime') or []:
                related_node = related.get('node') or {}
                related_anime_id = related_node.get('id')
                if not related_anime_id:
                    continue

                related_series = AnimeSeries(
                    anime_id=related_anime_id,
                    source='myanimelist',
                    mal_id=related_anime_id,
                    title_english=related_node.get('title'),
                    title_romanji=related_node.get('title'),
                    url='{base}/anime/{anime_id}'.format(base=self.BASE_URL, anime_id=related_anime_id),
                )

                relation_type = related.get('relation_type')
                if relation_type == 'prequel':
                    anime.prequels.append(related_series)
                elif relation_type == 'sequel':
                    anime.sequels.append(related_series)

        return anime

    def _enrich_with_scraped_detail_page(self, anime: AnimeSeries, mal_id: int) -> AnimeSeries:
        """Scrape the MAL detail page for cross refs and any fields the official API omits."""
        anime_url = self.ANIME_URL.format(anime_id=mal_id)
        soup = self._get(anime_url)
        if not soup:
            return anime

        try:
            scraped = self._parse_anime_details(soup, mal_id)
        except Exception as error:
            log.debug('Failed to enrich MAL API details from HTML for {mal_id}: {error}', mal_id=mal_id, error=error)
            return anime

        if not anime.anidb_id:
            anime.anidb_id = scraped.anidb_id
        if not anime.anilist_id:
            anime.anilist_id = scraped.anilist_id
        if not anime.tvdb_id:
            anime.tvdb_id = scraped.tvdb_id
        if not anime.image_url:
            anime.image_url = scraped.image_url
        if not anime.synopsis:
            anime.synopsis = scraped.synopsis
        if not anime.title_japanese:
            anime.title_japanese = scraped.title_japanese
        if not anime.title_romanji and scraped.title_romanji:
            anime.title_romanji = scraped.title_romanji
        if not anime.title_english and scraped.title_english:
            anime.title_english = scraped.title_english
        if not anime.title_synonyms and scraped.title_synonyms:
            anime.title_synonyms = scraped.title_synonyms

        return anime

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

        seasonal_entries = soup.find_all('div', class_=re.compile(r'(^|\s)(js-seasonal-anime|seasonal-anime)(\s|$)', re.I))
        if seasonal_entries:
            for entry in seasonal_entries:
                anime = self._parse_seasonal_entry(entry, year, season)
                if anime:
                    results.append(anime)
            return results

        # Older MAL layouts used tables; keep this as a compatibility fallback.
        anime_rows = soup.find_all('tr', class_=re.compile(r'anime-planning|anime-list-', re.I))
        if not anime_rows:
            seasonal_section = soup.find('table', class_=re.compile(r'seasonal', re.I))
            if seasonal_section:
                anime_rows = seasonal_section.find_all('tr')
            else:
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

    def _parse_seasonal_entry(self, entry, year: int, season: str) -> Optional[AnimeSeries]:
        """Parse anime data from MAL's current seasonal card layout."""
        try:
            title_link = entry.find('a', class_=re.compile(r'link-title', re.I))
            if not title_link:
                title_link = entry.find('a', href=re.compile(r'/anime/\d+'))
            if not title_link:
                return None

            href = title_link.get('href', '')
            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                return None

            anime_id = int(anime_id_match.group(1))
            title = title_link.get_text(strip=True) or entry.find('span', class_='js-title')
            if not isinstance(title, str):
                title = title.get_text(strip=True) if title else None
            if not title:
                return None

            synopsis = None
            synopsis_block = entry.find('div', class_=re.compile(r'(^|\s)(js-synopsis|synopsis)(\s|$)', re.I))
            if synopsis_block:
                synopsis_text = synopsis_block.get_text(' ', strip=True)
                synopsis = synopsis_text or None

            image_url = None
            image = entry.find('img')
            if image:
                image_url = image.get('data-src') or image.get('src')

            score = None
            score_node = entry.find('span', class_='js-score')
            if score_node:
                score_text = score_node.get_text(strip=True)
                try:
                    score = float(score_text) if score_text and score_text != 'N/A' else None
                except ValueError:
                    score = None

            episodes = None
            duration_minutes = None
            info_items = entry.select('div.prodsrc div.info span.item')
            if len(info_items) >= 2:
                info_text = info_items[1].get_text(' ', strip=True)
                episode_match = re.search(r'(\d+)\s*eps?', info_text, re.I)
                if episode_match:
                    episodes = int(episode_match.group(1))
                duration_match = re.search(r'(\d+)\s*min', info_text, re.I)
                if duration_match:
                    duration_minutes = int(duration_match.group(1))

            genres = []
            for genre_link in entry.select('div.genres a'):
                genre = genre_link.get_text(strip=True)
                if genre:
                    genres.append(genre)

            anime_type = 'TV'
            type_classes = ' '.join(entry.get('class') or [])
            if 'js-anime-type-2' in type_classes:
                anime_type = 'MOVIE'
            elif 'js-anime-type-3' in type_classes:
                anime_type = 'OVA'
            elif 'js-anime-type-4' in type_classes:
                anime_type = 'SPECIAL'
            elif 'js-anime-type-5' in type_classes:
                anime_type = 'ONA'

            url = f"{self.BASE_URL}{href}" if href.startswith('/') else href

            anime = AnimeSeries(
                anime_id=anime_id,
                source='myanimelist',
                mal_id=anime_id,
                title_english=title,
                title_romanji=title,
                synopsis=synopsis,
                image_url=image_url,
                episodes=episodes,
                episode_duration_minutes=duration_minutes,
                score=score,
                genres=genres,
                anime_type=anime_type,
                url=url,
                year=year,
                season=season,
            )

            return anime
        except Exception as error:
            log.debug('Failed to parse seasonal entry: {error}', error=error)
            return None

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
            if not title:
                image = link.find('img') or (link.parent.find('img') if link.parent else None)
                title = (image.get('alt') if image else '') or ''
            title = title.strip()
            if not title:
                return None
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
            title_section = soup.find('h1', class_=re.compile(r'title-name|h1_bold_none|se-title', re.I))
            if not title_section:
                title_section = soup.find('section', class_='header-title')

            if title_section:
                title_elem = title_section.find(['strong', 'span'])
                if title_elem:
                    anime.title_romanji = title_elem.get_text(strip=True)
                else:
                    anime.title_romanji = title_section.get_text(strip=True)

            # Get alternative titles from MAL's current hidden alternative-title block.
            title_alt = soup.find('div', class_=re.compile(r'js-alternative-titles|title-alt', re.I))
            if title_alt:
                for alt_row in title_alt.find_all('div', class_=re.compile(r'spaceit_pad', re.I)):
                    label_node = alt_row.find('span', class_=re.compile(r'dark_text', re.I))
                    if not label_node:
                        continue

                    label = label_node.get_text(' ', strip=True).rstrip(':').lower()
                    value = alt_row.get_text(' ', strip=True)
                    value = value.replace(label_node.get_text(' ', strip=True), '', 1).strip()
                    if not value or value == 'None':
                        continue

                    if label == 'english':
                        anime.title_english = value
                    elif label == 'japanese':
                        anime.title_japanese = value
                    elif label == 'synonyms':
                        anime.title_synonyms = [item.strip() for item in value.split(',') if item.strip()]

            if not anime.title_english and anime.title_romanji:
                anime.title_english = anime.title_romanji

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
