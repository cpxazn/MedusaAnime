# coding=utf-8
"""Request handler for series operations."""
from __future__ import unicode_literals

import logging

from medusa import app, db, notifiers, ui, ws
from medusa.helper.exceptions import ShowDirectoryNotFoundException
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler
from medusa.server.api.v2.series import SeriesHandler
from medusa.tv.episode import Episode, EpisodeNumber
from medusa.tv.series import Series, SeriesIdentifier

from requests.compat import quote_plus

from tornado.escape import json_decode

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class SeriesOperationHandler(BaseRequestHandler):
    """Operation request handler for series."""

    #: parent resource handler
    parent_handler = SeriesHandler
    #: resource name
    name = 'operation'
    #: identifier
    identifier = None
    #: path param
    path_param = None
    #: allowed HTTP methods
    allowed_methods = ('POST', )

    def post(self, series_slug):
        """Query series information.

        :param series_slug: series slug. E.g.: tvdb1234
        """
        series_identifier = SeriesIdentifier.from_slug(series_slug)
        if not series_identifier:
            return self._bad_request('Invalid series slug')

        series = Series.find_by_identifier(series_identifier)
        if not series:
            return self._not_found('Series not found')

        data = json_decode(self.request.body)
        if not data or not all([data.get('type')]):
            return self._bad_request('Invalid request body')

        if data['type'] == 'ARCHIVE_EPISODES':
            if series.set_all_episodes_archived(final_status_only=True):
                return self._created()
            return self._no_content()

        if data['type'] == 'TEST_RENAME':
            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                return self._bad_request("Can't rename episodes when the show dir is missing.")

            filter_season = data.get('season')

            ep_obj_list = series.get_all_episodes(has_location=True, season=filter_season)
            ep_obj_list = [x for x in ep_obj_list if x.location]
            ep_obj_rename_list = []
            for ep_obj in ep_obj_list:
                has_already = False
                for check in ep_obj.related_episodes + [ep_obj]:
                    if check in ep_obj_rename_list:
                        has_already = True
                        break
                if not has_already:
                    ep_obj_rename_list.append(ep_obj)

            if ep_obj_rename_list:
                ep_obj_rename_list.reverse()
            return self._ok(data=[
                {**ep_obj.to_json(detailed=True), **{'selected': False}} for ep_obj in ep_obj_rename_list
            ])

        if data['type'] == 'RENAME_EPISODES':
            episodes = data.get('episodes', [])
            if not episodes:
                return self._bad_request('You must provide at least one episode')

            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                return self._bad_request("Can't rename episodes when the show dir is missing.")

            main_db_con = db.DBConnection()
            for episode_slug in episodes:
                episode_number = EpisodeNumber.from_slug(episode_slug)
                if not episode_number:
                    continue

                episode = Episode.find_by_series_and_episode(series, episode_number)
                if not episode:
                    continue

                # this is probably the worst possible way to deal with double eps
                # but I've kinda painted myself into a corner here with this stupid database
                ep_result = main_db_con.select(
                    'SELECT location '
                    'FROM tv_episodes '
                    'WHERE indexer = ? AND showid = ? AND season = ? AND episode = ? AND 5=5',
                    [series.indexer, series.series_id, episode.season, episode.episode])

                if not ep_result:
                    log.warning('Unable to find an episode for {episode}, skipping', {'episode': episode})
                    continue

                related_eps_result = main_db_con.select(
                    'SELECT season, episode '
                    'FROM tv_episodes '
                    'WHERE location = ? AND episode != ?',
                    [ep_result[0]['location'], episode.episode]
                )

                root_ep_obj = episode
                root_ep_obj.related_episodes = []

                for cur_related_ep in related_eps_result:
                    related_ep_obj = series.get_episode(cur_related_ep['season'], cur_related_ep['episode'])
                    if related_ep_obj not in root_ep_obj.related_episodes:
                        root_ep_obj.related_episodes.append(related_ep_obj)

                root_ep_obj.rename()
            return self._created()

        if data['type'] == 'ORGANIZE_SEASON_FOLDERS':
            """Move episodes into season subdirectories without renaming files.

            Enables seasonFolders on the series (if not already enabled) and
            moves all downloaded episode files into Season XX/ subdirectories,
            preserving the original filenames. Also moves associated files
            (subtitles, etc.).

            Plex struggles with multi-season anime in flat directories.
            Organizing into season subdirs fixes Plex detection issues.
            """
            import os
            import shutil

            from medusa import helpers
            from medusa.post_processor import PostProcessor

            try:
                series.validate_location  # @UnusedVariable
            except ShowDirectoryNotFoundException:
                return self._bad_request("Can't organize season folders when the show dir is missing.")

            # Enable season folders if not already set
            if not series.season_folders:
                series.season_folders = True
                series.save_to_db()
                log.info('Enabled season folders for {series}', {'series': series.name})

            show_dir = series.location
            main_db_con = db.DBConnection()

            # Get all episodes with file locations
            all_episodes = [ep for ep in series.get_all_episodes(has_location=True) if ep.location]

            # Deduplicate by location (related episodes share the same file).
            # When multiple episode records point to the same file (common in flat
            # directories where S2E01 was post-processed as both S01E01 and S02E01),
            # prefer the higher season number so files land in the correct folder.
            location_to_ep: dict[str, Episode] = {}
            for ep_obj in all_episodes:
                loc = ep_obj.location
                existing = location_to_ep.get(loc)
                if existing is None or ep_obj.season > existing.season:
                    location_to_ep[loc] = ep_obj
            unique_episodes = list(location_to_ep.values())

            moved: list[dict[str, str]] = []
            errors: list[dict[str, str]] = []

            for ep_obj in unique_episodes:
                old_path = ep_obj.location
                if not os.path.isfile(old_path):
                    errors.append({
                        'episode': f's{ep_obj.season:02d}e{ep_obj.episode:02d}',
                        'error': f'File not found: {old_path}',
                    })
                    continue

                # Determine target directory and path
                season_dir = os.path.join(show_dir, f'Season {ep_obj.season:02d}')
                filename = os.path.basename(old_path)
                new_path = os.path.join(season_dir, filename)

                # Already in the right place?
                if old_path == new_path:
                    continue

                try:
                    # Create season directory if needed
                    helpers.make_dirs(season_dir)

                    # Find related episodes (same location, different season/episode)
                    related_eps_result = main_db_con.select(
                        'SELECT season, episode '
                        'FROM tv_episodes '
                        'WHERE location = ? '
                        'AND NOT (season = ? AND episode = ?) '
                        'AND indexer = ? AND showid = ?',
                        [old_path, ep_obj.season, ep_obj.episode, series.indexer, series.series_id]
                    )
                    related_eps: list[Episode] = []
                    for rel in related_eps_result:
                        rel_ep = series.get_episode(rel['season'], rel['episode'])
                        if rel_ep and rel_ep not in related_eps:
                            related_eps.append(rel_ep)

                    # Move associated files (subtitles, etc.)
                    associated_files = PostProcessor(old_path).list_associated_files(
                        old_path, subfolders=True
                    )
                    for assoc_file in associated_files:
                        assoc_filename = os.path.basename(assoc_file)
                        assoc_new_path = os.path.join(season_dir, assoc_filename)
                        if assoc_file != assoc_new_path and os.path.isfile(assoc_file):
                            helpers.make_dirs(season_dir)
                            shutil.move(assoc_file, assoc_new_path)
                            log.debug(
                                'Moved associated file {old} -> {new}',
                                {'old': assoc_file, 'new': assoc_new_path}
                            )

                    # Move the main episode file
                    shutil.move(old_path, new_path)
                    log.info(
                        'Organized {ep} {old} -> {new}',
                        {'ep': ep_obj.pretty_name(), 'old': old_path, 'new': new_path}
                    )

                    # Update location for this episode and related episodes in DB
                    ep_obj.location = new_path
                    for rel_ep in related_eps:
                        rel_ep.location = new_path

                    # Save all updated locations to DB
                    sql_l = [ep_obj.get_sql()]
                    for rel_ep in related_eps:
                        sql_l.append(rel_ep.get_sql())
                    main_db_con.mass_action(sql_l)

                    moved.append({
                        'episode': f's{ep_obj.season:02d}e{ep_obj.episode:02d}',
                        'from': old_path,
                        'to': new_path,
                    })

                except (OSError, IOError) as error:
                    log.error(
                        'Failed to move {old} -> {new}: {error!r}',
                        {'old': old_path, 'new': new_path, 'error': error}
                    )
                    errors.append({
                        'episode': f's{ep_obj.season:02d}e{ep_obj.episode:02d}',
                        'error': str(error),
                    })

            # Push WebSocket update
            msg = ws.Message('showUpdated', series.to_json(detailed=False))
            msg.push()

            return self._ok(data={
                'seasonFoldersEnabled': True,
                'moved': moved,
                'errors': errors,
            })

        # This might also be moved to /notifications/kodi/update?showslug=..
        if data['type'] == 'UPDATE_KODI':
            series_name = quote_plus(series.name.encode('utf-8'))

            if app.KODI_UPDATE_ONLYFIRST:
                host = app.KODI_HOST[0].strip()
            else:
                host = ', '.join(app.KODI_HOST)

            if notifiers.kodi_notifier.update_library(series_name=series_name):
                ui.notifications.message(f'Library update command sent to KODI host(s): {host}')
            else:
                ui.notifications.error(f'Unable to contact one or more KODI host(s): {host}')

            return self._created()

        return self._bad_request('Invalid operation')
