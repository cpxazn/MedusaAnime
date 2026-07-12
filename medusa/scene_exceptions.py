# coding=utf-8

"""Scene exceptions module."""

from __future__ import unicode_literals

import gzip
import io
import logging
import os
import time
from collections import defaultdict, namedtuple
from os.path import join

from medusa import app, db
from medusa.helpers import sanitize_scene_name
from medusa.indexers.api import indexerApi
from medusa.indexers.config import INDEXER_TVDBV2
from medusa.logger.adapters.style import BraceAdapter
from medusa.session.core import MedusaSafeSession

from requests.compat import urljoin

from six import iteritems

logger = BraceAdapter(logging.getLogger(__name__))
logger.logger.addHandler(logging.NullHandler())

exceptions_cache = defaultdict(lambda: defaultdict(set))
VALID_XEM_ORIGINS = {'anidb', 'tvdb', }
safe_session = MedusaSafeSession()

TitleException = namedtuple('TitleException', 'title, season, indexer, series_id, custom')


def refresh_exceptions_cache(series_obj=None):
    """
    Query the db for show exceptions and update the exceptions_cache.

    :param series_obj: Series Object. If passed only exceptions for this show are refreshed.
    """
    logger.info('Updating exception_cache and exception_season_cache')

    # Empty the module level variables
    if not series_obj:
        exceptions_cache.clear()
    else:
        exceptions_cache[(series_obj.indexer, series_obj.series_id)].clear()

    main_db_con = db.DBConnection()
    query = """
        SELECT indexer, series_id, title, season, custom
        FROM scene_exceptions
    """
    where = []

    if series_obj:
        query += ' WHERE indexer = ? AND series_id = ?'
        where += [series_obj.indexer, series_obj.series_id]

    exceptions = main_db_con.select(query, where) or []

    # Start building up a new exceptions_cache.
    for exception in exceptions:
        indexer = int(exception['indexer'])
        series_id = int(exception['series_id'])
        season = int(exception['season'])
        title = exception['title']
        custom = bool(exception['custom'])

        # To support multiple indexers with same series_id, we have to combine the min a tuple.
        series = (indexer, series_id)
        series_exception = TitleException(
            title=title,
            season=season,
            indexer=indexer,
            series_id=series_id,
            custom=custom
        )

        # exceptions_cache[(1, 12345)][season] =
        # TitleExeption('title', 'season', indexer, series_id)
        if series_exception not in exceptions_cache[series][season]:
            exceptions_cache[series][season].add(series_exception)

    logger.info('Finished processing {x} scene exceptions.', x=len(exceptions))


def get_last_refresh(ex_list):
    """Get the last update timestamp for the specific scene exception list."""
    cache_db_con = db.DBConnection('cache.db')
    return cache_db_con.select('SELECT last_refreshed FROM scene_exceptions_refresh WHERE list = ?', [ex_list])


def should_refresh(ex_list):
    """
    Check if we should refresh cache for items in ex_list.

    :param ex_list: exception list to check if exception needs a refresh
    :return: True if refresh is needed
    """
    max_refresh_age_secs = 86400  # 1 day
    rows = get_last_refresh(ex_list)

    if rows:
        last_refresh = int(rows[0]['last_refreshed'])
        return int(time.time()) > last_refresh + max_refresh_age_secs
    else:
        return True


def set_last_refresh(source):
    """
    Update last cache update time for shows in list.

    :param source: scene exception source refreshed (e.g. xem)
    """
    cache_db_con = db.DBConnection('cache.db')
    cache_db_con.upsert(
        'scene_exceptions_refresh',
        {'last_refreshed': int(time.time())},
        {'list': source}
    )


def get_scene_exceptions(series_obj, season=-1):
    """Get scene exceptions from exceptions_cache for a series."""
    exceptions_list = exceptions_cache[(series_obj.indexer, series_obj.series_id)][season]

    if season != -1 and not exceptions_list:
        exceptions_list = get_scene_exceptions(series_obj)

    # Return a set to avoid duplicates and it makes a copy of the list so the
    # original doesn't get modified
    return set(exceptions_list)


def get_season_scene_exceptions(series_obj, season=-1):
    """
    Get season scene exceptions from exceptions_cache for a series.

    Use this method if you expect to get back a season exception, or a series exception.
    But without any fallback between the two. As opposed to the function get_scene_exceptions.
    :param series_obj: A Series object.
    :param season: The season to return exceptions for. Or -1 for the series exceptions.

    :return: A set of exception names.
    """
    exceptions_list = exceptions_cache[(series_obj.indexer, series_obj.series_id)][season]

    # Return a set to avoid duplicates and it makes a copy of the list so the
    # original doesn't get modified
    return set(exceptions_list)


def get_season_from_name(series_obj, exception_name):
    """
    Get season number from exceptions_cache for a series scene exception name.

    Use this method if you expect to get back a season number from a scene exception.
    :param series_obj: A Series object.
    :param series_name: The scene exception name.

    :return: The season number or None.
    """
    exceptions_list = exceptions_cache[(series_obj.indexer, series_obj.series_id)]
    for season, exceptions in exceptions_list.items():
        # Skip whole series exceptions
        if season == -1:
            continue
        for exception in exceptions:
            if exception.title.lower() == exception_name.lower():
                return exception.season


def get_all_scene_exceptions(series_obj):
    """
    Get all scene exceptions for a show object using indexer and series_id.

    :param series_obj: series object.
    :return: dict of exceptions (e.g. exceptions_cache[season][exception_name])
    """
    return exceptions_cache.get((series_obj.indexer, series_obj.series_id), defaultdict(set))


def get_scene_exception_by_name(series_name):
    """Get the season of a scene exception."""
    # Flatten the exceptions_cache.
    scene_exceptions = []
    for exception_set in list(exceptions_cache.values()):
        for title_exception in list(exception_set.values()):
            scene_exceptions += title_exception

    # First attempt exact match.
    for title_exception in scene_exceptions:
        if series_name == title_exception.title:
            return title_exception

    # Let's try out some sanitized names.
    for title_exception in scene_exceptions:
        sanitized_name = sanitize_scene_name(title_exception.title)
        titles = (
            title_exception.title.lower(),
            sanitized_name.lower().replace('.', ' '),
        )

        if series_name.lower() in titles:
            logger.debug(
                'Scene exception lookup got series id {title_exception.series_id} '
                'from indexer {title_exception.indexer},'
                ' using that', title_exception=title_exception
            )
            return title_exception


def update_scene_exceptions(series_obj, scene_exceptions):
    """
    Update database with all show scene exceptions by indexer_id.

    :param series_obj: series object.
    :param scene_exceptions: list of dicts, originating from the /config/ apiv2 route. Where scene exceptions are set from the UI.
    """
    logger.info('Updating scene exceptions...')

    main_db_con = db.DBConnection()

    exceptions_cache[(series_obj.indexer, series_obj.series_id)].clear()
    # Remove exceptions for this show, so removed exceptions also become visible.
    main_db_con.action(
        'DELETE FROM scene_exceptions '
        'WHERE series_id=? AND indexer=?',
        [series_obj.series_id, series_obj.indexer]
    )

    for exception in scene_exceptions:
        # A change has been made to the scene exception list.

        # Prevent adding duplicate scene exceptions.
        if exception['title'] not in exceptions_cache[(series_obj.indexer, series_obj.series_id)][exception['season']]:
            # Add to db
            main_db_con.action(
                'INSERT INTO scene_exceptions '
                '(indexer, series_id, title, season, custom) '
                'VALUES (?,?,?,?,?)',
                [series_obj.indexer, series_obj.series_id, exception['title'], exception['season'], exception['custom']]
            )

    refresh_exceptions_cache(series_obj)


def retrieve_exceptions(force=False, exception_type=None):
    """
    Look up the exceptions from all sources.

    Parses the exceptions into a dict, and inserts them into the
    scene_exceptions table in cache.db. Also clears the scene name cache.
    :param force: If enabled this will force the refresh of scene exceptions using the medusa exceptions,
    xem exceptions and anidb exceptions.
    :param exception_type: Only refresh a specific exception_type. Options are: 'medusa', 'anidb', 'xem'
    """
    custom_exceptions = _get_custom_exceptions(force) if exception_type in ['custom_exceptions', None] else defaultdict(dict)
    xem_exceptions = _get_xem_exceptions(force) if exception_type in ['xem', None] else defaultdict(dict)
    anidb_exceptions = _get_anidb_exceptions(force) if exception_type in ['anidb', None] else defaultdict(dict)

    # Combined scene exceptions from all sources
    combined_exceptions = combine_exceptions(
        # Custom scene exceptions
        custom_exceptions,
        # XEM scene exceptions
        xem_exceptions,
        # AniDB scene exceptions
        anidb_exceptions,
    )

    queries = []
    main_db_con = db.DBConnection()

    # TODO: See if this can be optimized
    for indexer in combined_exceptions:
        for series_id in combined_exceptions[indexer]:
            sql_ex = main_db_con.select(
                'SELECT title, indexer '
                'FROM scene_exceptions '
                'WHERE indexer = ? AND '
                'series_id = ?',
                [indexer, series_id]
            )
            existing_exceptions = [x['title'] for x in sql_ex]

            for exception_dict in combined_exceptions[indexer][series_id]:
                for scene_exception, season in iteritems(exception_dict):
                    if scene_exception not in existing_exceptions:
                        queries.append([
                            'INSERT OR IGNORE INTO scene_exceptions'
                            '(indexer, series_id, title, season, custom) '
                            'VALUES (?,?,?,?,?)',
                            [indexer, series_id, scene_exception, season, False]
                        ])
    if queries:
        main_db_con.mass_action(queries)
        logger.info('Updated scene exceptions.')


def combine_exceptions(*scene_exceptions):
    """Combine the exceptions from all sources."""
    # ex_dicts = iter(scene_exceptions)
    combined_ex = defaultdict(dict)

    for scene_exception in scene_exceptions:
        for indexer in scene_exception or []:
            combined_ex[indexer].update(scene_exception[indexer])

    return combined_ex


def _get_custom_exceptions(force):
    """Exceptions maintained by the medusa.github.io repo."""
    custom_exceptions = defaultdict(dict)

    if force or should_refresh('custom_exceptions'):
        for indexer in indexerApi().indexers:
            location = indexerApi(indexer).config['scene_loc']
            logger.info(
                'Checking for scene exception updates from {location}',
                location=location
            )
            try:
                # When any Medusa Safe session exception, session returns None and then AttributeError when json()
                jdata = safe_session.get(location, timeout=60).json()
            except (ValueError, AttributeError) as error:
                logger.debug(
                    'Check scene exceptions update failed. Unable to '
                    'update from {location}. Error: {error}'.format(
                        location=location, error=error
                    )
                )
                # If unable to get scene exceptions, assume we can't connect to CDN so we don't `continue`
                return custom_exceptions

            indexer_ids = jdata[indexerApi(indexer).config['identifier']]
            for indexer_id in indexer_ids:
                indexer_exceptions = indexer_ids[indexer_id]
                alias_list = [{exception: int(season)}
                              for season in indexer_exceptions
                              for exception in indexer_exceptions[season]]
                custom_exceptions[indexer][indexer_id] = alias_list

            set_last_refresh('custom_exceptions')

    return custom_exceptions


def _get_xem_exceptions(force):
    xem_exceptions = defaultdict(dict)
    url = urljoin(app.XEM_URL, '/map/allNames')
    params = {
        'origin': None,
        'seasonNumbers': 1,
    }

    if force or should_refresh('xem'):
        for indexer in indexerApi().indexers:
            indexer_api = indexerApi(indexer)

            try:
                # Get XEM origin for indexer
                origin = indexer_api.config['xem_origin']
                if origin not in VALID_XEM_ORIGINS:
                    msg = 'invalid origin for XEM: {0}'.format(origin)
                    raise ValueError(msg)
            except KeyError:
                # Indexer has no XEM origin
                continue
            except ValueError as error:
                # XEM origin for indexer is invalid
                logger.error(
                    'Error getting XEM scene exceptions for {indexer}:'
                    ' {error}', {'indexer': indexer_api.name, 'error': error}
                )
                continue
            else:
                # XEM origin for indexer is valid
                params['origin'] = origin

            logger.info(
                'Checking for XEM scene exceptions updates for'
                ' {indexer_name}', {'indexer_name': indexer_api.name}
            )

            response = safe_session.get(url, params=params, timeout=60)
            try:
                jdata = response.json()
            except (ValueError, AttributeError) as error:
                logger.debug(
                    'Check scene exceptions update failed for {indexer}.'
                    ' Unable to get URL: {url} Error: {error}', {'indexer': indexer_api.name, 'url': url, 'error': error}
                )
                continue

            if not jdata['data'] or jdata['result'] == 'failure':
                logger.debug(
                    'No data returned from XEM while checking for scene'
                    ' exceptions. Update failed for {indexer}', {'indexer': indexer_api.name}
                )
                continue

            for indexer_id, exceptions in iteritems(jdata['data']):
                try:
                    xem_exceptions[indexer][indexer_id] = exceptions
                except Exception as error:
                    logger.warning(
                        'XEM: Rejected entry: Indexer ID: {indexer_id},'
                        ' Exceptions: {exceptions}', {'indexer_id': indexer_id, 'exceptions': exceptions}
                    )
                    logger.warning('XEM: Rejected entry error message: {error}', {'error': error})

        set_last_refresh('xem')

    return xem_exceptions


def _get_anidb_exceptions(force):
    """
    Fetch scene exceptions from AniDB's daily anime-titles dump.

    Downloads and extracts https://anidb.net/api/anime-titles.dat.gz, respecting
    a 24-hour cooldown to avoid rate-limit bans. Parses the pipe-delimited DAT
    format (aid|type|language|title) and extracts English synonyms (type 2)
    and short titles (type 3) for every anime show in the library that has
    a stored AniDB ID.

    The AniDB ID is stored per-series as an external mapping:
        series.externals['anidb_id']  (EXTERNAL_ANIDB = 11)
    """
    anidb_exceptions = defaultdict(dict)
    exceptions = anidb_exceptions[INDEXER_TVDBV2]

    if not force and not should_refresh('anidb'):
        return anidb_exceptions

    logger.info('Checking for scene exceptions updates from AniDB')

    # 1. Download and parse the DAT dump: {anidb_id: [english titles]}
    aid_to_titles = _parse_anidb_titles_dump()
    if not aid_to_titles:
        logger.warning('AniDB titles dump was empty or could not be parsed')
        return anidb_exceptions

    # 2. Walk all anime shows in the library and attach exceptions.
    for show in app.showList:
        if not all([show.is_anime, show.indexer == INDEXER_TVDBV2]):
            continue

        anidb_id = show.externals.get('anidb_id')
        if not anidb_id:
            continue

        # Ensure aid is an int for dict lookup against the parsed DAT data.
        try:
            aid = int(anidb_id)
        except (ValueError, TypeError):
            continue

        titles = aid_to_titles.get(aid)
        if not titles:
            continue

        tvdb_id = int(show.series_id)
        # Build exception list: each entry is {title: season}, -1 = series-level
        exception_list = [{title: -1} for title in titles]
        exceptions[tvdb_id] = exception_list

    set_last_refresh('anidb')
    return anidb_exceptions


def _parse_anidb_titles_dump():
    """
    Download (if needed) and parse the AniDB anime-titles.dat.gz dump.

    Returns a dict: {anidb_id: set of English synonym/short titles}

    The DAT format is: <aid>|<type>|<language>|<title>
    Types: 1=primary, 2=synonyms, 3=short titles, 4=official titles
    We only care about types 2 (synonyms) and 3 (short) in language 'en'.
    """
    cache_dir = join(app.CACHE_DIR, 'anidb')
    os.makedirs(cache_dir, exist_ok=True)
    dat_path = join(cache_dir, 'anime-titles.dat')

    # Download the gz file if the dat file is missing or older than 24h.
    if _should_download_anidb_dump(dat_path):
        if not _download_anidb_titles_dat(dat_path):
            return {}

    # Parse the DAT file line by line.
    aid_to_titles = {}
    try:
        with io.open(dat_path, encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip comments and empty lines
                if not line or line.startswith('#'):
                    continue
                # Split into exactly 4 parts: aid|type|language|title
                parts = line.split('|', 3)
                if len(parts) != 4:
                    continue
                aid, type_str, language, title = parts
                aid = int(aid)
                # Only English synonyms (2) and short titles (3)
                if language != 'en' or type_str not in ('2', '3'):
                    continue
                aid_to_titles.setdefault(aid, set()).add(title)
    except Exception as error:
        logger.error('AniDB titles DAT parse failed: {error}', {'error': error})
        return {}

    # Convert sets to lists for JSON-serializable output.
    return {aid: list(titles) for aid, titles in aid_to_titles.items()}


def _should_download_anidb_dump(dat_path):
    """
    Check whether the AniDB dump needs re-downloading.

    AniDB restricts downloads to once per 24 hours to prevent abuse.
    If the local dat file exists and is less than 24h old, skip download.
    """
    if not os.path.isfile(dat_path):
        return True
    try:
        mtime = os.path.getmtime(dat_path)
        return (time.time() - mtime) > 86400  # 24 hours
    except OSError:
        return True


def _download_anidb_titles_dat(dat_path):
    """
    Download and extract the AniDB anime-titles.dat.gz dump.

    Returns True if successful, False otherwise.
    """
    url = 'https://anidb.net/api/anime-titles.dat.gz'
    gz_path = dat_path + '.gz'

    try:
        logger.info('Downloading AniDB anime titles dump from {url}', {'url': url})
        response = safe_session.get(url, timeout=120, stream=True)
        response.raise_for_status()

        # Write gz file first, then extract to dat.
        with open(gz_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)

        # Extract gz to dat.
        with gzip.open(gz_path, 'rb') as gz_file:
            with open(dat_path, 'wb') as out_file:
                out_file.write(gz_file.read())

        # Remove gz file.
        os.remove(gz_path)
        logger.info('AniDB titles dump extracted successfully')
        return True
    except Exception as error:
        logger.error('AniDB titles download failed: {error}', {'error': error})
        # Clean up partial files.
        for path in (gz_path, dat_path):
            if os.path.isfile(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        return False
