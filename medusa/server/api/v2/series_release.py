# coding=utf-8
"""Request handler for series release group configuration, search, and diagnosis."""
from __future__ import unicode_literals

import logging

from medusa import app
from medusa.common import (
    DOWNLOADED,
    Quality,
    statusStrings,
)
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler
from medusa.server.api.v2.series import SeriesHandler
from medusa.tv.series import Series, SeriesIdentifier

from tornado.escape import json_decode

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class SeriesReleaseHandler(BaseRequestHandler):
    """Release group config request handler for series."""

    #: parent resource handler
    parent_handler = SeriesHandler
    #: resource name
    name = 'release'
    #: identifier
    identifier = None
    #: path param (handles both /release and /release/search)
    path_param = ('path_param', r'\w+')
    #: allowed HTTP methods
    allowed_methods = ('GET', 'POST')

    def get(self, series_slug, path_param=None):
        """Return release group configuration for a series.

        :param series_slug: series slug. E.g.: tvdb1234
        """
        if path_param:
            return self._bad_request('Invalid path parameter: {0}'.format(path_param))

        series_identifier = SeriesIdentifier.from_slug(series_slug)
        if not series_identifier:
            return self._bad_request('Invalid series slug')

        series = Series.find_by_identifier(series_identifier)
        if not series:
            return self._not_found('Series not found')

        whitelist = series.whitelist or []
        data = {
            'whitelist': whitelist,
            'blacklist': series.blacklist or [],
            'fallbackGroups': series.anime_release_group_fallback_groups or [],
            'fallbackDays': series.anime_release_group_fallback_days,
            'lastSwitch': series.anime_release_group_last_switch,
            'activeGroup': whitelist[0] if whitelist else None,
        }

        return self._ok(data=data)

    def post(self, series_slug, path_param=None):
        """Dispatch to search or diagnose based on path_param.

        POST /api/v2/series/{slug}/release/search
        POST /api/v2/series/{slug}/release/diagnose

        :param series_slug: series slug. E.g.: tvdb1234
        :param path_param: 'search' or 'diagnose'
        """
        if path_param == 'search':
            return self._search(series_slug)
        elif path_param == 'diagnose':
            return self._diagnose(series_slug)
        else:
            return self._bad_request(
                'Invalid path parameter: {0}. Use /release/search or /release/diagnose'.format(path_param)
            )

    # --- Search ---

    def _search(self, series_slug):
        """Trigger a search for the episode and return aggregated release groups + qualities.

        POST /api/v2/series/{slug}/release/search
        Optional JSON body: {"season": 1, "episode": 1} (defaults to episode 1)
        """
        series_identifier = SeriesIdentifier.from_slug(series_slug)
        if not series_identifier:
            return self._bad_request('Invalid series slug')

        series = Series.find_by_identifier(series_identifier)
        if not series:
            return self._not_found('Series not found')

        data = {}
        if self.request.body:
            try:
                data = json_decode(self.request.body)
            except (ValueError, AttributeError):
                pass

        season = int(data.get('season', 1))
        episode = int(data.get('episode', 1))

        # Get the episode object
        ep_obj = series.get_episode(season, episode)
        if isinstance(ep_obj, str):
            return self._not_found('Episode {s}x{e:02d} not found'.format(s=season, e=episode))
        if not ep_obj:
            return self._not_found('Episode {s}x{e:02d} not found'.format(s=season, e=episode))

        episode_info = self._build_episode_info(season, episode, ep_obj)

        # If already downloaded, no need to search
        if episode_info['downloaded']:
            return self._ok(data={
                'episode': episode_info,
                'searchTriggered': False,
                'results': [],
            })

        # Import here to avoid circular dependencies
        from medusa.search.manual import get_provider_cache_results

        # Trigger search and get cached results
        provider_results = get_provider_cache_results(
            series,
            show_all_results=False,
            perform_search=True,
            season=season,
            episode=episode,
            manual_search_type='episode',
        )

        error = provider_results.get('error')
        if error:
            log.warning('Error during release group search for {series} {ep}: {error}',
                        {'series': series.name,
                         'ep': '{s}x{e:02d}'.format(s=season, e=episode),
                         'error': error})

        # Aggregate results by (release_group, quality)
        aggregated = {}
        for item in provider_results.get('found_items', []):
            rg = item.get('release_group') or 'None'
            quality_num = int(item.get('quality', 0))
            key = (rg, quality_num)

            if key not in aggregated:
                quality_names = Quality.split_quality(quality_num)
                aggregated[key] = {
                    'releaseGroup': rg,
                    'quality': quality_num,
                    'qualityName': (
                        quality_names[0] if quality_names
                        else Quality.qualityStrings.get(quality_num, 'Unknown')
                    ),
                    'count': 0,
                    'providers': set(),
                }

            aggregated[key]['count'] += 1
            aggregated[key]['providers'].add(item.get('provider', 'Unknown'))

        # A search was triggered when no cached results returned
        search_triggered = len(provider_results.get('found_items', [])) == 0

        results = []
        for agg in aggregated.values():
            agg['providers'] = sorted(agg['providers'])
            results.append(agg)

        # Sort: most common first, then highest quality first
        results.sort(key=lambda r: (-r['count'], -r['quality']))

        return self._ok(data={
            'episode': episode_info,
            'searchTriggered': search_triggered,
            'results': results,
        })

    # --- Diagnose ---

    def _diagnose(self, series_slug):
        """Deterministic diagnosis: compare release config vs search results.

        POST /api/v2/series/{slug}/release/diagnose
        Optional JSON body: {"season": 1, "episode": 1} (defaults to episode 1)

        Returns a single response with config, available groups, and diagnosis.
        """
        series_identifier = SeriesIdentifier.from_slug(series_slug)
        if not series_identifier:
            return self._bad_request('Invalid series slug')

        series = Series.find_by_identifier(series_identifier)
        if not series:
            return self._not_found('Series not found')

        # Must be anime
        if not series.is_anime:
            return self._bad_request('Show must be anime')

        data = {}
        if self.request.body:
            try:
                data = json_decode(self.request.body)
            except (ValueError, AttributeError):
                pass

        season = int(data.get('season', 1))
        episode = int(data.get('episode', 1))

        # Get the episode object (no_create=False means it will be created if missing)
        ep_obj = series.get_episode(season, episode)
        if isinstance(ep_obj, str):
            return self._not_found('Episode {s}x{e:02d} not found'.format(s=season, e=episode))
        if not ep_obj:
            return self._not_found('Episode {s}x{e:02d} not found'.format(s=season, e=episode))

        episode_info = self._build_episode_info(season, episode, ep_obj)

        # Case 1: Already downloaded
        if episode_info['downloaded']:
            return self._ok(data={
                'diagnosis': {
                    'code': 'already_downloaded',
                    'summary': 'Episode {s}x{e:02d} is already downloaded. Release groups are not the issue.'.format(
                        s=season, e=episode),
                },
                'config': self._get_release_config(series),
                'episode': episode_info,
                'availableGroups': [],
                'searchTriggered': False,
            })

        # Import here to avoid circular dependencies
        from medusa.search.manual import get_provider_cache_results

        # Read-only cache check (perform_search=False — don't trigger search yet)
        provider_results = get_provider_cache_results(
            series,
            show_all_results=False,
            perform_search=False,
            season=season,
            episode=episode,
            manual_search_type='episode',
        )

        cached_items = provider_results.get('found_items', [])

        # Case 2: Cache empty, queue a manual search
        if not cached_items:
            from medusa.search.queue import ManualSearchQueueItem

            ep_queue_item = ManualSearchQueueItem(series, [ep_obj], 'episode')
            app.forced_search_queue_scheduler.action.add_item(ep_queue_item)

            return self._ok(data={
                'diagnosis': {
                    'code': 'search_in_progress',
                    'summary': 'No cached results found. A manual search has been queued. Retry in a few seconds.',
                },
                'config': self._get_release_config(series),
                'episode': episode_info,
                'availableGroups': [],
                'searchTriggered': True,
            })

        # Cases 3-5: Results available — aggregate and diagnose
        available_groups = self._aggregate_results(cached_items)
        config = self._get_release_config(series)
        diagnosis = self._diagnose_release_group_issue(config, available_groups)

        return self._ok(data={
            'diagnosis': diagnosis,
            'config': config,
            'episode': episode_info,
            'availableGroups': available_groups,
            'searchTriggered': False,
        })

    # --- Helpers ---

    @staticmethod
    def _build_episode_info(season, episode, ep_obj):
        """Build episode info dict from episode object."""
        return {
            'season': season,
            'episode': episode,
            'downloaded': ep_obj.status >= DOWNLOADED,
            'status': statusStrings.get(ep_obj.status, 'Unknown'),
            'quality': Quality.qualityStrings.get(ep_obj.quality, 'Unknown'),
        }

    @staticmethod
    def _get_release_config(series):
        """Extract release group configuration from series object."""
        whitelist = series.whitelist or []
        return {
            'whitelist': whitelist,
            'blacklist': series.blacklist or [],
            'fallbackGroups': series.anime_release_group_fallback_groups or [],
            'fallbackDays': series.anime_release_group_fallback_days,
            'lastSwitch': series.anime_release_group_last_switch,
            'activeGroup': whitelist[0] if whitelist else None,
        }

    @staticmethod
    def _aggregate_results(cached_items):
        """Aggregate cached provider results by (release_group, quality).

        Returns a sorted list of dicts (most common + highest quality first).
        """
        aggregated = {}
        for item in cached_items:
            rg = item.get('release_group') or 'None'
            quality_num = int(item.get('quality', 0))
            key = (rg, quality_num)

            if key not in aggregated:
                quality_names = Quality.split_quality(quality_num)
                aggregated[key] = {
                    'releaseGroup': rg,
                    'quality': quality_num,
                    'qualityName': (
                        quality_names[0] if quality_names
                        else Quality.qualityStrings.get(quality_num, 'Unknown')
                    ),
                    'count': 0,
                    'providers': set(),
                }

            aggregated[key]['count'] += 1
            aggregated[key]['providers'].add(item.get('provider', 'Unknown'))

        results = []
        for agg in aggregated.values():
            agg['providers'] = sorted(agg['providers'])
            results.append(agg)

        results.sort(key=lambda r: (-r['count'], -r['quality']))
        return results

    @staticmethod
    def _diagnose_release_group_issue(config, available_groups):
        """Run deterministic diagnosis rules against config and available groups.

        Rules are evaluated in priority order. The first matching rule wins.
        Returns a dict with 'code', 'summary', and optional 'recommendation'.
        """
        whitelist = config.get('whitelist') or []
        blacklist = config.get('blacklist') or []
        available_release_groups = {g['releaseGroup'] for g in available_groups}

        # Rule: No releases found at all
        if not available_groups:
            return {
                'code': 'no_releases_found',
                'summary': 'No releases found for this episode from any enabled provider.',
                'recommendation': None,
            }

        # Rule: Blacklist is blocking all available groups (check before whitelist rule
        # so the user gets actionable info about blocked groups)
        if blacklist and available_release_groups.issubset(set(blacklist)):
            return {
                'code': 'blacklist_blocking_all',
                'summary': 'All available release groups are blacklisted.',
                'recommendation': {
                    'action': 'remove_from_blacklist',
                    'targetGroups': sorted(available_release_groups),
                    'reason': 'Blacklist is blocking the only available release groups',
                },
            }

        # Rule: Whitelist has entries, none appear in results
        if whitelist and not any(rg in available_release_groups for rg in whitelist):
            best_group = SeriesReleaseHandler._pick_best_group(available_groups, blacklist)
            if best_group:
                return {
                    'code': 'whitelist_group_not_found',
                    'summary': "Whitelisted group '{old}' has no releases. "
                               "'{new}' is available with {count} releases.".format(
                                   old=whitelist[0],
                                   new=best_group['releaseGroup'],
                                   count=best_group['count']),
                    'recommendation': {
                        'action': 'replace_whitelist',
                        'targetGroups': [best_group['releaseGroup']],
                        'reason': 'Only group with confirmed releases for this episode',
                    },
                }
            return {
                'code': 'no_releases_found',
                'summary': 'No releases found for this episode from any enabled provider.',
                'recommendation': None,
            }

        # Rule: Whitelisted group exists in results — config is fine
        if whitelist:
            present = [rg for rg in whitelist if rg in available_release_groups]
            if present:
                group = present[0]
                count = sum(g['count'] for g in available_groups if g['releaseGroup'] == group)
                return {
                    'code': 'config_ok',
                    'summary': "Whitelisted group '{group}' has {count} releases available. "
                               "No changes needed.".format(group=group, count=count),
                    'recommendation': None,
                }

        # Rule: No whitelist configured but results exist — suggest one
        if not whitelist and available_groups:
            best_group = SeriesReleaseHandler._pick_best_group(available_groups, blacklist)
            if best_group:
                return {
                    'code': 'no_whitelist_configured',
                    'summary': "No release group is configured. '{group}' is available "
                               "with {count} releases.".format(
                                   group=best_group['releaseGroup'],
                                   count=best_group['count']),
                    'recommendation': {
                        'action': 'replace_whitelist',
                        'targetGroups': [best_group['releaseGroup']],
                        'reason': 'No release group is currently configured for this series',
                    },
                }

        # Fallback: shouldn't reach here given the rules above
        return {
            'code': 'unknown',
            'summary': 'Unable to determine release group issue.',
            'recommendation': None,
        }

    @staticmethod
    def _pick_best_group(available_groups, blacklist=None):
        """Pick the best release group from available results.

        Best = highest count first, then highest quality.
        Skips blacklisted groups.
        """
        blacklist = blacklist or []
        candidates = [g for g in available_groups if g['releaseGroup'] not in blacklist]
        if not candidates:
            return None
        candidates.sort(key=lambda r: (-r['count'], -r['quality']))
        return candidates[0]
