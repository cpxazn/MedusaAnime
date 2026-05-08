# coding=utf-8
"""Request handler for anime lookup from LiveChart.me and MyAnimeList."""
from __future__ import unicode_literals

import logging

from medusa import app
from medusa.clients.anime import AnimeSeries
from medusa.clients.livechart import LiveChartClient
from medusa.clients.myanimelist import MyAnimeListClient
from medusa.helpers.anime_matcher import match_anime_to_show, find_similar_anime
from medusa.indexers.config import EXTERNAL_ANIDB
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler
from medusa.show.recommendations.recommended import cached_aid_to_tvdb
from medusa.tv.series import Series

from tornado.escape import json_decode

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class AnimeHandler(BaseRequestHandler):
    """Request handler for anime lookup from external sources."""

    #: resource name
    name = 'anime'
    #: identifier
    identifier = ('identifier', r'\w+')
    #: path param
    path_param = ('path_param', r'\w+')
    #: allowed HTTP methods
    allowed_methods = ('GET', 'POST')

    #: Source mapping
    SOURCE_MAP = {
        'livechart': LiveChartClient,
        'myanimelist': MyAnimeListClient,
    }

    def get(self, identifier, path_param=None):
        """Query anime information.

        Args:
            identifier: Source identifier ('livechart', 'myanimelist', 'search', 'seasonal', 'upcoming')
            path_param: Optional path parameter
        """
        if identifier == 'search':
            # Search by query string
            query = self.get_argument('q', default=None)
            source = self.get_argument('source', default='livechart')
            year = self._parse(self.get_argument('year', default=None))
            season = self.get_argument('season', default=None)

            if not query:
                return self._bad_request('Search query parameter "q" is required')

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            try:
                results = client.search(query)
            except Exception as error:
                log.warning('Search failed: {error}', error=error)
                return self._internal_server_error(str(error))

            # Add match info for each result
            data = []
            for anime in results:
                show = match_anime_to_show(anime)
                anime_data = self._anime_to_json(anime)
                anime_data['matched'] = show is not None
                if show:
                    anime_data['match'] = {
                        'slug': show.identifier.slug,
                        'title': show.title,
                    }
                data.append(anime_data)

            return self._paginate(data, sort='-year')

        elif identifier == 'seasonal':
            # Get seasonal anime
            year = self._parse(self.get_argument('year', default=None))
            season = self.get_argument('season', default=None)
            source = self.get_argument('source', default='livechart')

            if not year:
                return self._bad_request('Year parameter is required for seasonal queries')

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            try:
                results = client.get_seasonal(year, season or 'SPRING')
            except Exception as error:
                log.warning('Seasonal fetch failed: {error}', error=error)
                return self._internal_server_error(str(error))

            data = [self._anime_to_json(anime) for anime in results]
            return self._paginate(data, sort='-year')

        elif identifier == 'upcoming':
            # Get upcoming anime
            source = self.get_argument('source', default='livechart')
            limit = self._parse(self.get_argument('limit', default=20))

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            try:
                results = client.get_upcoming(limit=limit)
            except Exception as error:
                log.warning('Upcoming fetch failed: {error}', error=error)
                return self._internal_server_error(str(error))

            data = [self._anime_to_json(anime) for anime in results]
            return self._paginate(data, sort='-year')

        elif identifier == 'details':
            # Get anime details
            anime_id = self._parse(self.get_argument('id', default=None))
            source = self.get_argument('source', default='livechart')

            if not anime_id:
                return self._bad_request('Anime ID parameter is required')

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            try:
                anime = client.get_details(anime_id)
            except Exception as error:
                log.warning('Details fetch failed: {error}', error=error)
                return self._internal_server_error(str(error))

            if not anime.anime_id:
                return self._not_found('Anime not found')

            # Add match info
            show = match_anime_to_show(anime)
            data = self._anime_to_json(anime)
            data['matched'] = show is not None
            if show:
                data['match'] = {
                    'slug': show.identifier.slug,
                    'title': show.title,
                }

            return self._ok(data)

        elif identifier == 'match':
            # Match anime to existing shows
            anime_id = self._parse(self.get_argument('id', default=None))
            source = self.get_argument('source', default='livechart')
            limit = self._parse(self.get_argument('limit', default=10))

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            try:
                anime = client.get_details(anime_id)
            except Exception as error:
                log.warning('Details fetch failed: {error}', error=error)
                return self._internal_server_error(str(error))

            if not anime.anime_id:
                return self._bad_request('Invalid anime ID')

            # Find similar shows
            similar = find_similar_anime(anime, limit=limit)
            
            data = {
                'anime': self._anime_to_json(anime),
                'matches': [
                    {
                        'slug': show.identifier.slug,
                        'title': show.title,
                        'score': score,
                    }
                    for show, score in similar
                ]
            }

            return self._ok(data)

        else:
            return self._bad_request('Invalid identifier. Use: search, seasonal, upcoming, details, match')

    def post(self, identifier, path_param=None):
        """Add anime to Medusa library.

        Args:
            identifier: Should be 'add' to add an anime
        """
        if identifier != 'add':
            return self._bad_request('Invalid identifier. Use: add')

        data = json_decode(self.request.body)
        if not data:
            return self._bad_request('Request body is required')

        # Extract anime data
        anime_id = data.get('anime_id')
        source = data.get('source', 'livechart')
        root_dir = data.get('root_dir')
        anime_option = data.get('anime', True)
        release_groups = data.get('release_groups', [])
        whitelist = data.get('whitelist', [])
        blacklist = data.get('blacklist', [])

        if not anime_id:
            return self._bad_request('anime_id is required')

        # Get the client and fetch anime details
        client = self._get_client(source)
        if not client:
            return self._bad_request('Invalid source. Use: livechart, myanimelist')

        try:
            anime_obj = client.get_details(anime_id)
        except Exception as error:
            log.warning('Details fetch failed: {error}', error=error)
            return self._internal_server_error(str(error))

        if not anime_obj.anime_id:
            return self._not_found('Anime not found')

        # Check if already in library
        existing_show = match_anime_to_show(anime_obj)
        if existing_show:
            return self._conflict('Anime already exists in library: {0}'.format(existing_show.title))

        # Generate directory name
        dir_name = data.get('directory_name', None)
        if not dir_name:
            dir_name = anime_obj.directory_name

        # Build the identifier for the show queue
        # Try to find the TVDB ID via cross-references
        identifier_str = None
        indexer_id = EXTERNAL_ANIDB
        indexer_value = anime_obj.anime_id

        if anime_obj.anidb_id:
            try:
                tvdb_id = cached_aid_to_tvdb(anime_obj.anidb_id)
                if tvdb_id:
                    identifier_str = 'tvdb{0}'.format(tvdb_id)
                    indexer_id = 'tvdb'
                    indexer_value = tvdb_id
            except Exception:
                pass

        if not identifier_str:
            # Use AniDB as fallback
            if not anime_obj.anidb_id:
                return self._bad_request('Could not find a valid indexer ID for this anime')
            identifier_str = 'anidb{0}'.format(anime_obj.anidb_id)
            indexer_id = 'anidb'
            indexer_value = anime_obj.anidb_id

        # Build options
        options = {
            'default_status': data.get('status', 'wanted'),
            'anime': anime_option,
            'scene': data.get('scene', True),
            'root_dir': root_dir,
            'blacklist': blacklist or (blacklist if blacklist else None),
            'whitelist': whitelist or (whitelist if whitelist else None),
        }

        if release_groups:
            options['whitelist'] = release_groups

        try:
            from medusa.indexers.utils import slug_to_indexer_id
            
            # Create identifier
            if isinstance(indexer_id, str):
                indexer_id = slug_to_indexer_id(indexer_id)
            
            queue_item_obj = app.show_queue_scheduler.action.addShow(
                indexer_id, indexer_value, dir_name, **options
            )
        except Exception as error:
            log.warning('Failed to add anime to queue: {error}', error=error)
            return self._internal_server_error(str(error))

        return self._created(data=queue_item_obj.to_json)

    def _get_client(self, source: str):
        """Get the appropriate anime client.
        
        Args:
            source: Source identifier
            
        Returns:
            Anime client instance or None
        """
        client_class = self.SOURCE_MAP.get(source)
        if client_class:
            return client_class()
        return None

    def _anime_to_json(self, anime: AnimeSeries) -> dict:
        """Convert AnimeSeries to JSON-serializable dict.
        
        Args:
            anime: AnimeSeries object
            
        Returns:
            Dictionary suitable for JSON response
        """
        return {
            'animeId': anime.anime_id,
            'source': anime.source,
            'titleJapanese': anime.title_japanese,
            'titleRomanji': anime.title_romanji,
            'titleEnglish': anime.title_english,
            'titleSynonyms': anime.title_synonyms,
            'synopsis': anime.synopsis,
            'animeType': anime.anime_type,
            'status': anime.status,
            'startDate': anime.start_date,
            'endDate': anime.end_date,
            'season': anime.season,
            'year': anime.year,
            'episodes': anime.episodes,
            'score': anime.score,
            'genres': anime.genres,
            'tags': anime.tags,
            'imageUrl': anime.image_url,
            'anidbId': anime.anidb_id,
            'anilistId': anime.anilist_id,
            'tvdbId': anime.tvdb_id,
            'malId': anime.mal_id,
            'url': anime.url,
            'displayTitle': anime.display_title,
            'directoryName': anime.directory_name,
        }


class AnimeRecommendedHandler(BaseRequestHandler):
    """Request handler for anime recommendations from AniList."""

    name = 'anime/recommended'
    identifier = ('identifier', r'\w+')
    path_param = ('path_param', r'\w+')
    allowed_methods = ('GET', 'POST')

    def get(self, identifier, path_param=None):
        """Get anime recommendations.
        
        Args:
            identifier: Year (e.g., '2026') or season (e.g., 'spring')
        """
        from medusa.show.recommendations.anilist import AniListPopular

        try:
            year = int(identifier) if identifier else None
            season = path_param.upper() if path_param else None

            if not year:
                from datetime import datetime
                now = datetime.now()
                year = now.year
                season = 'SPRING'

            if not season:
                season = 'SPRING'

            anilist = AniListPopular()
            shows = anilist.fetch_popular_shows(year, season)

            data = [show.to_json() for show in shows]
            return self._paginate(data, sort='-rating')

        except Exception as error:
            log.warning('Failed to get recommendations: {error}', error=error)
            return self._internal_server_error(str(error))
