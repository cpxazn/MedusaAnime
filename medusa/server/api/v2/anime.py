# coding=utf-8
"""Request handler for anime lookup from LiveChart.me and MyAnimeList."""
from __future__ import unicode_literals

import logging
import os
import re

from medusa import app
from medusa.common import statusStrings
from medusa.clients.anime import AnimeSeries
from medusa.clients.livechart import LiveChartClient
from medusa.clients.myanimelist import MyAnimeListClient
from medusa.helpers.anime_matcher import match_anime_to_show, find_similar_anime
from medusa.indexers.api import indexerApi
from medusa.indexers.config import INDEXER_TVDBV2
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler
from medusa.show.recommendations.recommended import cached_aid_to_tvdb
from medusa.tv.series import Series

from tornado.escape import json_decode

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class AnimeHandler(BaseRequestHandler):
    """Request handler for anime lookup from external sources."""

    SEASONAL_SORT_OPTIONS = ('anime_num_list_users', 'anime_score')

    #: resource name
    name = 'anime'
    #: identifier
    identifier = ('identifier', r'[\w-]+')
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
            source = self.get_argument('source', default='myanimelist')
            year = self._parse(self.get_argument('year', default=None))
            season = self.get_argument('season', default=None)
            include_details = self._parse_boolean(self.get_argument('includeDetails', default=False))
            fields = self._parse_fields(self.get_argument('fields', default=None))
            limit = self._get_limit(default=20)

            if not query:
                return self._bad_request('Search query parameter "q" is required')

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            try:
                results = client.search(query, include_details=include_details or bool(fields), limit=limit)
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
                data.append(self._project_fields(anime_data, fields))

            return self._paginate(data, sort='-year' if not fields or 'year' in fields else None)

        elif identifier == 'seasonal':
            # Get seasonal anime
            year = self._parse(self.get_argument('year', default=None))
            season = self.get_argument('season', default=None)
            source = self.get_argument('source', default='myanimelist')
            source_sort = self.get_argument('sourceSort', default='anime_num_list_users')
            anime_types = self._parse_fields(self.get_argument('animeType', default=None))
            min_num_list_users = self._parse(self.get_argument('minNumListUsers', default=None))
            include_genres = self._parse_fields(self.get_argument('includeGenres', default=None))
            exclude_genres = self._parse_fields(self.get_argument('excludeGenres', default=None))
            matched = self.get_argument('matched', default=None)
            matched = None if matched is None else self._parse_boolean(matched)
            fields = self._parse_fields(self.get_argument('fields', default=None))
            first_season_only = self._parse_boolean(self.get_argument('firstSeasonOnly', default=False))
            filtered_response = any([
                anime_types, min_num_list_users is not None, include_genres, exclude_genres,
                matched is not None, fields, first_season_only,
            ])

            if not year:
                return self._bad_request('Year parameter is required for seasonal queries')

            client = self._get_client(source)
            if not client:
                return self._bad_request('Invalid source. Use: livechart, myanimelist')

            if source_sort not in self.SEASONAL_SORT_OPTIONS:
                return self._bad_request(
                    'Invalid sourceSort. Use: {0}'.format(', '.join(self.SEASONAL_SORT_OPTIONS))
                )

            try:
                results = client.get_seasonal(year, season or 'SPRING', source_sort=source_sort)
            except Exception as error:
                log.warning('Seasonal fetch failed: {error}', error=error)
                return self._internal_server_error(str(error))

            data = []
            for anime in results:
                anime_data = self._anime_to_json(anime)
                if filtered_response:
                    show = match_anime_to_show(anime)
                    anime_data['matched'] = show is not None
                    if show:
                        anime_data['match'] = {
                            'slug': show.identifier.slug,
                            'title': show.title,
                        }
                data.append(anime_data)

            if filtered_response:
                data = self._filter_seasonal(
                    data,
                    anime_types=anime_types,
                    min_num_list_users=min_num_list_users,
                    include_genres=include_genres,
                    exclude_genres=exclude_genres,
                    matched=matched,
                    first_season_only=first_season_only,
                )
                data = [self._project_fields(anime, fields) for anime in data]
                return self._paginated_object(data)

            return self._paginate(data)

        elif identifier == 'upcoming':
            # Get upcoming anime
            source = self.get_argument('source', default='myanimelist')
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
            source = self.get_argument('source', default='myanimelist')

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
            source = self.get_argument('source', default='myanimelist')
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
        if identifier not in ('add', 'bulk-add'):
            return self._bad_request('Invalid identifier. Use: add, bulk-add')

        data = json_decode(self.request.body)
        if not data:
            return self._bad_request('Request body is required')

        if identifier == 'bulk-add':
            return self._bulk_add(data)

        result = self._add_anime_item(data)
        if result['success']:
            return self._created(data=result.get('queueItem'))
        if result['status'] == 404:
            return self._not_found(result['error'])
        if result['status'] == 409:
            return self._conflict(result['error'])
        if result['status'] >= 500:
            return self._internal_server_error(result['error'])
        return self._bad_request(result['error'])

    def _bulk_add(self, data):
        """Add or validate multiple anime items, returning per-item results."""
        defaults = data.get('defaults') or {}
        items = data.get('items') or []
        dry_run = self._parse_boolean(data.get('dry_run', False))
        verify = self._parse_boolean(data.get('verify', False))

        if not isinstance(defaults, dict):
            return self._bad_request('defaults must be an object')
        if not isinstance(items, list) or not items:
            return self._bad_request('items must be a non-empty list')

        results = []
        for item in items:
            if not isinstance(item, dict):
                results.append({
                    'animeId': None,
                    'success': False,
                    'action': 'invalid',
                    'matched': False,
                    'error': 'Bulk add item must be an object.',
                })
                continue

            item_data = defaults.copy()
            item_data.update(item)
            try:
                results.append(self._add_anime_item(item_data, dry_run=dry_run, verify=verify))
            except Exception as error:
                log.warning('Bulk anime add item failed unexpectedly: {error}', error=error)
                results.append({
                    'animeId': item_data.get('anime_id'),
                    'success': False,
                    'action': 'error',
                    'matched': False,
                    'error': str(error),
                })

        successes = len([result for result in results if result.get('success')])
        response = {
            'dryRun': dry_run,
            'requested': len(items),
            'successes': successes,
            'failures': len(items) - successes,
            'results': [self._clean_bulk_result(result) for result in results],
        }
        return self._ok(response)

    def _add_anime_item(self, data, dry_run=False, verify=False):
        """Validate and optionally queue one anime add request."""
        anime_id = data.get('anime_id')
        result = {
            'animeId': anime_id,
            'success': False,
            'action': 'invalid',
            'matched': False,
            'status': 400,
        }

        source = data.get('source', 'myanimelist')
        root_dir = data.get('root_dir')
        anime_option = data.get('anime', True)
        release_groups = data.get('release_groups', [])
        whitelist = data.get('whitelist', [])
        blacklist = data.get('blacklist', [])
        initial_release_group = data.get('initial_release_group')
        fallback_release_groups = data.get('fallback_release_groups')
        release_group_fallback_days = self._parse_optional_int(data.get('release_group_fallback_days'))

        if release_group_fallback_days is False:
            return self._item_error(result, 'Invalid release_group_fallback_days')

        if not anime_id:
            return self._item_error(result, 'anime_id is required')

        client = self._get_client(source)
        if not client:
            return self._item_error(result, 'Invalid source. Use: livechart, myanimelist')

        try:
            anime_obj = client.get_details(anime_id)
        except Exception as error:
            log.warning('Details fetch failed: {error}', error=error)
            return self._item_error(result, str(error), action='error', status=500)

        if not anime_obj.anime_id:
            return self._item_error(result, 'Anime not found', action='not_found', status=404)

        result['animeId'] = anime_obj.anime_id
        result['displayTitle'] = anime_obj.display_title

        existing_show = match_anime_to_show(anime_obj)
        if existing_show:
            result.update({
                'action': 'already_exists',
                'matched': True,
                'match': {
                    'slug': existing_show.identifier.slug,
                    'title': existing_show.title,
                } if getattr(existing_show, 'identifier', None) else {'title': existing_show.title},
                'status': 409,
                'error': 'Anime already exists in library: {0}'.format(existing_show.title),
            })
            return result

        dir_name = data.get('directory_name', None) or anime_obj.directory_name
        show_dir = dir_name
        if dir_name and root_dir and not os.path.isabs(dir_name):
            show_dir = os.path.join(root_dir, dir_name)

        if not anime_obj.anidb_id:
            return self._item_error(result, 'Could not resolve indexer ID for this anime')

        tvdb_id = self._resolve_tvdb_id(anime_obj)
        if not tvdb_id:
            return self._item_error(result, 'Could not map AniDB ID {0} to a TVDB ID'.format(anime_obj.anidb_id))

        default_status = self._parse_episode_status(data.get('status', 'wanted'))
        if default_status is None:
            return self._item_error(result, 'Invalid status')

        default_status_after = self._parse_episode_status(data.get('status_after'))
        options = {
            'default_status': default_status,
            'quality': data.get('quality', {'preferred': [], 'allowed': []}),
            'season_folders': data.get('season_folders'),
            'lang': data.get('language'),
            'subtitles': data.get('subtitles'),
            'anime': anime_option,
            'scene': data.get('scene', True),
            'paused': data.get('paused'),
            'root_dir': root_dir,
            'blacklist': blacklist or (blacklist if blacklist else None),
            'whitelist': whitelist or (whitelist if whitelist else None),
            'default_status_after': default_status_after,
            'show_lists': data.get('show_lists'),
        }

        if release_group_fallback_days is None:
            release_group_fallback_days = 3

        preferred_groups = fallback_release_groups or release_groups or whitelist or list(app.PREFERRED_ANIME_RELEASE_GROUPS) or ['SubsPlease']
        preferred_groups = [group for group in preferred_groups if group]
        active_group = initial_release_group or (preferred_groups[0] if preferred_groups else None)
        if active_group:
            preferred_groups = [group for group in preferred_groups if group.lower() != active_group.lower()]
            preferred_groups.insert(0, active_group)
            options['whitelist'] = [active_group]

        options['anime_release_group_fallback_groups'] = preferred_groups
        options['anime_release_group_fallback_days'] = release_group_fallback_days
        options['anime_release_group_last_switch'] = None

        result.update({
            'success': True,
            'action': 'would_add' if dry_run else 'added',
            'status': 200 if dry_run else 201,
            'matched': False,
            'message': 'Dry-run validation passed.' if dry_run else 'Anime queued for add.',
        })

        if dry_run:
            return result

        try:
            queue_item_obj = app.show_queue_scheduler.action.addShow(
                INDEXER_TVDBV2, tvdb_id, show_dir, **options
            )
        except Exception as error:
            log.warning('Failed to add anime to queue: {error}', error=error)
            return self._item_error(result, str(error), action='error', status=500)

        result['queueItem'] = queue_item_obj.to_json
        if verify:
            result['matched'] = match_anime_to_show(anime_obj) is not None
        return result

    @staticmethod
    def _parse_optional_int(value):
        """Parse an optional integer without raising, for per-item bulk errors."""
        if value is None:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _item_error(result, error, action='invalid', status=400):
        """Update a per-item result with an error."""
        result.update({
            'success': False,
            'action': action,
            'status': status,
            'error': error,
        })
        return result

    @staticmethod
    def _clean_bulk_result(result):
        """Remove internal response fields from bulk add item results."""
        cleaned = result.copy()
        cleaned.pop('status', None)
        cleaned.pop('queueItem', None)
        return cleaned

    @staticmethod
    def _parse_episode_status(status):
        """Parse an API status value into Medusa's numeric episode status."""
        if status in (None, ''):
            return None

        try:
            status_id = int(status)
        except (TypeError, ValueError):
            status_id = None

        if status_id in statusStrings:
            return status_id

        status_text = str(status).strip().lower()
        for status_id, status_name in statusStrings.items():
            if status_name.lower() == status_text:
                return status_id

        return None

    @staticmethod
    def _normalize_title(title):
        """Normalize a title for cross-source comparisons."""
        if not title:
            return ''
        return re.sub(r'[^a-z0-9]+', '', title.lower())

    def _tvdb_search_titles(self, anime: AnimeSeries):
        """Generate candidate titles to search on TVDB."""
        titles = [
            anime.title_english,
            anime.title_romanji,
            anime.title_japanese,
            anime.display_title,
        ]
        titles.extend(anime.title_synonyms or [])

        seen = set()
        for title in titles:
            normalized = self._normalize_title(title)
            if title and normalized and normalized not in seen:
                seen.add(normalized)
                yield title

    def _tvdb_result_matches(self, anime: AnimeSeries, result: dict) -> bool:
        """Return True when a TVDB search result is a safe match for this anime."""
        anime_titles = {self._normalize_title(title) for title in self._tvdb_search_titles(anime)}
        result_titles = [result.get('seriesname')]
        result_titles.extend((result.get('aliases') or '').split('|'))

        if not any(self._normalize_title(title) in anime_titles for title in result_titles):
            return False

        first_aired = result.get('firstaired') or ''
        if anime.year and first_aired[:4].isdigit() and int(first_aired[:4]) != anime.year:
            return False

        return True

    def _search_tvdb_id(self, anime: AnimeSeries):
        """Fallback to TVDB search when AniDB's mapping list does not know this anime yet."""
        try:
            tvdb_api = indexerApi(INDEXER_TVDBV2)
            tvdb = tvdb_api.indexer(**tvdb_api.api_params)
        except Exception as error:
            log.warning('Unable to initialize TVDB search for {title}: {error}', title=anime.display_title, error=error)
            return None

        for title in self._tvdb_search_titles(anime):
            try:
                results = tvdb.search(title) or []
            except Exception as error:
                log.debug('TVDB search failed for {title}: {error}', title=title, error=error)
                continue

            for result in results:
                if self._tvdb_result_matches(anime, result):
                    return result.get('id')

        return None

    def _resolve_tvdb_id(self, anime: AnimeSeries):
        """Resolve a TVDB ID for an anime using AniDB mapping, then TVDB title search."""
        if anime.tvdb_id:
            return anime.tvdb_id

        if anime.anidb_id:
            try:
                tvdb_id = cached_aid_to_tvdb(anime.anidb_id)
                if tvdb_id:
                    return tvdb_id
            except Exception as error:
                log.warning(
                    'Failed to map AniDB ID {anidb_id} to TVDB ID: {error}',
                    anidb_id=anime.anidb_id,
                    error=error
                )

        tvdb_id = self._search_tvdb_id(anime)
        if tvdb_id:
            log.info('Resolved TVDB ID {tvdb_id} for {title} using TVDB search fallback', {
                'tvdb_id': tvdb_id,
                'title': anime.display_title,
            })
        return tvdb_id

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

    def _paginated_object(self, data):
        """Return object-shaped pagination metadata for filtered seasonal responses."""
        page = self._get_page()
        limit = self._get_limit()
        total = len(data)
        start = (page - 1) * limit
        end = start + limit

        return self._ok(data={
            'items': data[start:end],
            'page': page,
            'limit': limit,
            'total': total,
            'hasNextPage': end < total,
        })

    @classmethod
    def _filter_seasonal(cls, data, anime_types=None, min_num_list_users=None, include_genres=None,
                         exclude_genres=None, matched=None, first_season_only=False):
        """Filter seasonal anime response dictionaries before pagination."""
        anime_types = cls._normalize_filter_values(anime_types)
        include_genres = cls._normalize_filter_values(include_genres)
        exclude_genres = cls._normalize_filter_values(exclude_genres)
        filtered = []

        for anime in data:
            if anime_types and cls._normalize_value(anime.get('animeType')) not in anime_types:
                continue

            num_list_users = anime.get('numListUsers')
            if min_num_list_users is not None and (num_list_users is None or num_list_users < min_num_list_users):
                continue

            genres = cls._normalize_filter_values(anime.get('genres') or [])
            if include_genres and not include_genres.intersection(genres):
                continue
            if exclude_genres and exclude_genres.intersection(genres):
                continue

            if matched is not None and anime.get('matched') is not matched:
                continue

            if first_season_only and cls._is_likely_later_season(anime):
                continue

            filtered.append(anime)

        return filtered

    @classmethod
    def _is_likely_later_season(cls, anime):
        """Heuristic to exclude sequels and continuations from seasonal results."""
        haystack = ' '.join(filter(None, [
            anime.get('displayTitle'),
            anime.get('titleEnglish'),
            anime.get('titleRomanji'),
            anime.get('synopsis'),
        ])).lower()

        patterns = (
            r'\b(second|third|fourth|fifth|sixth|seventh|eighth|ninth|tenth) season\b',
            r'\bseason\s*[2-9]\b',
            r'\bs[2-9]\b',
            r'\bpart\s*[2-9]\b',
            r'\b(sequel|continuation) to\b',
            r'\b(final|second|third) part of\b',
        )
        return any(re.search(pattern, haystack) for pattern in patterns)

    @staticmethod
    def _normalize_filter_values(values):
        """Normalize string/list filter values for case-insensitive comparisons."""
        if not values:
            return set()
        return {AnimeHandler._normalize_value(value) for value in values if value is not None}

    @staticmethod
    def _normalize_value(value):
        """Normalize a scalar value for case-insensitive comparisons."""
        return str(value).strip().lower()

    @staticmethod
    def _parse_fields(fields):
        """Parse a comma-separated field projection list."""
        if not fields:
            return None

        parsed = [field.strip() for field in fields.split(',') if field.strip()]
        return parsed or None

    @staticmethod
    def _project_fields(data, fields):
        """Return only requested response fields when a projection is supplied."""
        if not fields:
            return data

        return {field: data.get(field) for field in fields}

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
            'episodeDurationMinutes': anime.episode_duration_minutes,
            'episodeInfo': anime.episode_info,
            'score': anime.score,
            'numListUsers': anime.num_list_users,
            'genres': anime.genres,
            'tags': anime.tags,
            'studios': anime.studios,
            'nextEpisodeNumber': anime.next_episode_number,
            'nextEpisodeRelease': anime.next_episode_release,
            'nextEpisodeCountdown': anime.next_episode_countdown,
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
