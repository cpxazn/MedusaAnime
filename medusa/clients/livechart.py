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
    # Seasonal URL pattern: /spring-2026/tv  (/ for current season)
    SEASONAL_URL = f'{BASE_URL}/{{season}}-{{year}}/tv'
    CURRENT_SEASON_URL = BASE_URL + '/'
    RATE_LIMIT = 5  # requests per second

    # Map internal season names to livechart URL slugs
    SEASON_SLUG = {
        'WINTER': 'winter',
        'SPRING': 'spring',
        'SUMMER': 'summer',
        'FALL': 'fall',
    }

    def __init__(self):
        """Initialize the LiveChart client."""
        self.session = MedusaSession()
        self.session.headers.update({
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
        if not query:
            return results

        def normalize(value):
            return re.sub(r'[^a-z0-9]+', ' ', (value or '').strip().lower()).strip()

        def matches_query(anime_obj):
            needle = normalize(query)
            if not needle:
                return True

            haystacks = [
                normalize(anime_obj.title_romanji),
                normalize(anime_obj.title_english),
                normalize(anime_obj.title_japanese),
                normalize(anime_obj.display_title),
            ]
            return any(h and needle in h for h in haystacks)

        # Build search URL - livechart.me uses /search?q=query
        search_url = self.SEARCH_URL.format(query=query)
        soup = self._get(search_url)

        if not soup:
            return results

        # Parse structured article cards first (preferred).
        anime_cards = soup.find_all('article', class_='anime')
        if not anime_cards:
            # Fallback: link-based search results.
            anime_cards = soup.find_all('a', href=re.compile(r'/anime/\d+'))

        seen = set()
        for card in anime_cards[:100]:
            anime = self._parse_anime_from_card(card)
            if anime and anime.anime_id not in seen and matches_query(anime):
                seen.add(anime.anime_id)
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

        # Build the season-specific URL: /spring-2026/tv
        season_slug = self.SEASON_SLUG.get((season or '').upper())
        if season_slug:
            url = self.SEASONAL_URL.format(season=season_slug, year=year)
        else:
            url = self.CURRENT_SEASON_URL

        soup = self._get(url)
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
        soup = self._get(self.CURRENT_SEASON_URL)

        if not soup:
            return []

        return self._parse_anime_list(soup, limit=limit)

    def _parse_anime_from_article(self, article, year: Optional[int] = None,
                                  season: Optional[str] = None) -> Optional[AnimeSeries]:
        """Parse anime data from a livechart.me <article class="anime"> element.

        livechart.me stores all key metadata as data-* attributes on the article tag,
        with synopsis in div.anime-synopsis and image in div.poster-container > img.

        Args:
            article: BeautifulSoup <article class="anime"> element
            year: Season year (passed from the API query, not parsed from HTML)
            season: Season name e.g. 'SPRING' (passed from the API query)

        Returns:
            AnimeSeries or None
        """
        try:
            # --- IDs and titles from data attributes ---
            anime_id_str = article.get('data-anime-id')
            if not anime_id_str:
                return None
            anime_id = int(anime_id_str)

            title_romanji = article.get('data-romaji') or None
            title_english = article.get('data-english') or None
            title_japanese = article.get('data-native') or None

            # --- Image ---
            poster_div = article.find('div', class_='poster-container')
            img = poster_div.find('img') if poster_div else None
            image_url = img.get('src') or img.get('data-src') if img else None

            # --- Synopsis ---
            synopsis_div = article.find('div', class_='anime-synopsis')
            synopsis = synopsis_div.get_text(strip=True) if synopsis_div else None

            # --- Anime type from schedule info: e.g. "EP6 · TV (JP)" ---
            anime_type = 'TV'
            next_episode_number = None
            next_episode_countdown = None
            sched_div = article.find('div', class_='release-schedule-info')
            if sched_div:
                sched_text = sched_div.get_text(' ', strip=True)
                type_match = re.search(
                    r'\b(TV Special|TV|Movie|OVA|ONA|OND|Short)\b', sched_text, re.I
                )
                if type_match:
                    anime_type = type_match.group(1)

                ep_match = re.search(r'\bEP\s*(\d+)\b', sched_text, re.I)
                if ep_match:
                    try:
                        next_episode_number = int(ep_match.group(1))
                    except ValueError:
                        pass

                countdown_match = re.search(r'(\d+d\s+\d+h\s+\d+m\s+\d+s|Released)', sched_text, re.I)
                if countdown_match:
                    next_episode_countdown = countdown_match.group(1)

            # --- Score ---
            score = None
            score_div = article.find('div', class_='anime-avg-user-rating')
            if score_div:
                try:
                    score = float(score_div.get_text(strip=True))
                except (ValueError, TypeError):
                    pass

            # --- Genres from tag links (/tags/NN) ---
            genres = [
                a.get_text(strip=True)
                for a in article.find_all('a', href=re.compile(r'/tags/\d+'))
            ]

            # --- Premiere date from Unix timestamp ---
            start_date = None
            premiere_ts = article.get('data-premiere')
            if premiere_ts:
                try:
                    dt = datetime.utcfromtimestamp(int(premiere_ts))
                    start_date = dt.strftime('%Y-%m-%d')
                    # Only derive year/season from premiere if not supplied
                    if year is None:
                        year = dt.year
                    if season is None:
                        season = self._month_to_season(dt.month)
                except (ValueError, TypeError, OSError):
                    pass

            # --- Episode count ---
            episodes = None
            episode_duration_minutes = None
            episode_info = None
            ep_div = article.find('div', class_='anime-episodes')
            if ep_div:
                episode_info = ep_div.get_text(strip=True)

                ep_match = re.search(r'(\d+)\s*ep', episode_info, re.I)
                if ep_match:
                    try:
                        episodes = int(ep_match.group(1))
                    except ValueError:
                        pass

                runtime_match = re.search(r'×\s*(\d+)\s*m', episode_info, re.I)
                if runtime_match:
                    try:
                        episode_duration_minutes = int(runtime_match.group(1))
                    except ValueError:
                        pass

            # --- Studio names ---
            studios = [
                a.get_text(strip=True)
                for a in article.find_all('a', href=re.compile(r'/studios/\d+'))
            ]

            # --- Upcoming/air date text ---
            next_episode_release = None
            date_div = article.find('div', class_='anime-date')
            if date_div:
                next_episode_release = date_div.get_text(' ', strip=True)

            return AnimeSeries(
                anime_id=anime_id,
                source='livechart',
                title_romanji=title_romanji,
                title_english=title_english,
                title_japanese=title_japanese,
                synopsis=synopsis,
                anime_type=anime_type,
                image_url=image_url,
                score=score,
                genres=genres,
                studios=studios,
                season=season,
                year=year,
                start_date=start_date,
                episodes=episodes,
                episode_duration_minutes=episode_duration_minutes,
                episode_info=episode_info,
                next_episode_number=next_episode_number,
                next_episode_release=next_episode_release,
                next_episode_countdown=next_episode_countdown,
                url='{base}/anime/{id}'.format(base=self.BASE_URL, id=anime_id),
            )
        except Exception as error:
            log.debug('Failed to parse anime article: {error}', error=error)
            return None

    def _parse_anime_from_card(self, card) -> Optional[AnimeSeries]:
        """Parse anime data from a search result card.

        Delegates to _parse_anime_from_article when the element is an
        <article class="anime">, otherwise falls back to link-based parsing.

        Args:
            card: BeautifulSoup element representing an anime card

        Returns:
            AnimeSeries object or None
        """
        # Prefer the structured article format
        if card.name == 'article' and 'anime' in (card.get('class') or []):
            return self._parse_anime_from_article(card)

        try:
            # Fallback: find the title link by anime URL pattern
            if card.name == 'a' and card.get('href'):
                link = card
            else:
                link = card.find('a', href=re.compile(r'/anime/\d+$'))
            if not link:
                link = card.find('a', href=True)
            if not link:
                return None

            href = link['href']
            anime_id_match = re.search(r'/anime/(\d+)', href)
            if not anime_id_match:
                return None

            anime_id = int(anime_id_match.group(1))
            title = link.get_text(strip=True) or None

            # Search pages often keep poster <img> outside the title <a>; look up to list item.
            if card.name == 'a':
                image_root = card.find_parent('li') or card.parent
            else:
                image_root = card

            img = image_root.find('img') if image_root else None
            image_url = img.get('src') or img.get('data-src') if img else None

            url = '{base}{href}'.format(base=self.BASE_URL, href=href) if href.startswith('/') else href

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
        """Parse a list of anime from a livechart.me seasonal page.

        Args:
            soup: Parsed HTML of the seasonal page
            year: Year for the season (e.g. 2026); set on every returned AnimeSeries
            season: Season name (e.g. 'SPRING'); set on every returned AnimeSeries
            limit: Optional maximum number of results

        Returns:
            List of AnimeSeries objects
        """
        results = []

        # livechart.me wraps each anime in <article class="anime">
        articles = soup.find_all('article', class_='anime')

        for article in articles:
            if limit and len(results) >= limit:
                break

            anime = self._parse_anime_from_article(article, year=year, season=season)
            if anime:
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
            # --- Try JSON-LD structured data first (most reliable) ---
            ld_json = self._extract_ld_json(soup)
            if ld_json:
                self._apply_ld_json(anime, ld_json)

            # --- HTML-based title extraction (only if JSON-LD was absent/incomplete) ---
            title_section = soup.find('section', id=re.compile(r'anime-title', re.I))
            if not title_section:
                title_section = soup.find('h1') or soup.find('h2')

            if title_section:
                # Only look for Japanese text in real content elements, never in <script>/<style>
                for s in title_section.find_all(string=re.compile(r'[\u4e00-\u9fff\u3040-\u30ff]', re.U)):
                    if s.parent and s.parent.name not in ('script', 'style'):
                        if not anime.title_japanese:
                            anime.title_japanese = s.strip()
                        break

                romanji_elem = title_section.find(class_=re.compile(r'romanji|title-romanji', re.I))
                if romanji_elem and not anime.title_romanji:
                    anime.title_romanji = romanji_elem.get_text(strip=True)

                english_elem = title_section.find(class_=re.compile(r'english|title-english', re.I))
                if english_elem and not anime.title_english:
                    anime.title_english = english_elem.get_text(strip=True)

                synonym_elem = title_section.find(class_=re.compile(r'synonym', re.I))
                if synonym_elem:
                    syns = synonym_elem.get_text(strip=True)
                    anime.title_synonyms = [s.strip() for s in syns.split(',') if s.strip()]

            # Synopsis/Description
            if not anime.synopsis:
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

            # External IDs (AniDB, AniList, MAL, TVDB)
            for link in soup.find_all('a', href=True):
                href = (link.get('href') or '').replace('&amp;', '&')
                if not href:
                    continue

                if 'anidb.net' in href and not anime.anidb_id:
                    anidb_match = re.search(r'aid=(\d+)', href)
                    if anidb_match:
                        anime.anidb_id = int(anidb_match.group(1))

                if 'anilist.co/anime/' in href and not anime.anilist_id:
                    anilist_match = re.search(r'/anime/(\d+)', href)
                    if anilist_match:
                        anime.anilist_id = int(anilist_match.group(1))

                if 'myanimelist.net/anime/' in href and not anime.mal_id:
                    mal_match = re.search(r'/anime/(\d+)', href)
                    if mal_match:
                        anime.mal_id = int(mal_match.group(1))

                if 'thetvdb.com' in href and not anime.tvdb_id:
                    tvdb_match = re.search(r'/series/(\d+)', href)
                    if tvdb_match:
                        anime.tvdb_id = int(tvdb_match.group(1))

        except Exception as error:
            log.debug('Failed to parse anime details for ID {anime_id}: {error}', anime_id=anime_id, error=error)

        return anime

    def _extract_ld_json(self, soup: BeautifulSoup) -> Optional[dict]:
        """Extract and parse the first application/ld+json script block from the page."""
        import json
        script = soup.find('script', type='application/ld+json')
        if not script:
            return None
        try:
            return json.loads(script.get_text())
        except Exception:
            return None

    def _apply_ld_json(self, anime: AnimeSeries, ld: dict) -> None:
        """Populate AnimeSeries fields from a schema.org JSON-LD object."""
        import re as _re

        # schema.org TVSeries / Movie: 'name' is typically the romanji/primary title
        name = ld.get('name') or ''
        if name:
            anime.title_romanji = name

        alternate_names = ld.get('alternateName') or []
        if isinstance(alternate_names, str):
            alternate_names = [alternate_names]

        jp_re = _re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uff00-\uffef]')
        for alt in alternate_names:
            if jp_re.search(alt) and not anime.title_japanese:
                anime.title_japanese = alt
            elif not jp_re.search(alt) and not anime.title_english and alt != name:
                anime.title_english = alt

        description = ld.get('description') or ''
        if description:
            anime.synopsis = description

        episodes = ld.get('numberOfEpisodes')
        if episodes and not anime.episodes:
            try:
                anime.episodes = int(episodes)
            except (TypeError, ValueError):
                pass

        date_published = ld.get('datePublished') or ''
        if date_published and not anime.start_date:
            anime.start_date = date_published[:10]
            try:
                anime.year = int(date_published[:4])
            except (TypeError, ValueError):
                pass

        genres = ld.get('genre') or []
        if isinstance(genres, str):
            genres = [genres]
        if genres and not anime.genres:
            anime.genres = genres

        image = ld.get('image') or ''
        if image and not anime.image_url:
            anime.image_url = image

        url = ld.get('url') or ''
        if url and not anime.url:
            anime.url = url

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
