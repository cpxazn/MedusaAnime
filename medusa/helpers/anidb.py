"""Helper for anidb communications."""
from __future__ import unicode_literals

import logging
import re
from os.path import join

import adba
from adba.aniDBerrors import AniDBCommandTimeoutError
from adba.aniDBfileInfo import read_anidb_xml

from medusa import app
from medusa.cache import anidb_cache
from medusa.helper.exceptions import AnidbAdbaConnectionException
from medusa.logger.adapters.style import BraceAdapter
from medusa.show.recommendations.recommended import create_key

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


def _normalize_title_for_aid_lookup(title):
    """Normalize title for loose AniDB title matching."""
    if not title:
        return ''

    value = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip().lower()
    # Drop punctuation and whitespace to match variations like "Himekishi" vs "Hime Kishi".
    return re.sub(r'[^a-z0-9]+', '', value)


def _tokenize_title_for_aid_lookup(title):
    """Tokenize title for loose AniDB XML fallback matching."""
    if not title:
        return []

    value = re.sub(r'\s*\(\d{4}\)\s*$', '', title).strip().lower()
    return re.findall(r'[a-z0-9]+', value)


def _get_aid_from_xml_loose(series_name, cache_path):
    """Best-effort AniDB aid lookup from animetitles.xml with exact then ranked loose match."""
    target = _normalize_title_for_aid_lookup(series_name)
    if not target:
        return 0

    xml_titles = read_anidb_xml(cache_path)
    if not xml_titles:
        return 0

    try:
        # Stage 1: normalized exact match.
        for anime in xml_titles.findall('anime'):
            aid = int(anime.get('aid') or 0)
            if not aid:
                continue

            for title in anime.findall('title'):
                title_text = title.text or ''
                if _normalize_title_for_aid_lookup(title_text) == target:
                    return aid

        # Stage 2: ranked loose token overlap.
        target_tokens = _tokenize_title_for_aid_lookup(series_name)
        if not target_tokens:
            return 0

        target_unique = set(target_tokens)
        best_match = None

        for anime in xml_titles.findall('anime'):
            aid = int(anime.get('aid') or 0)
            if not aid:
                continue

            for title in anime.findall('title'):
                title_text = title.text or ''
                title_tokens = _tokenize_title_for_aid_lookup(title_text)
                if not title_tokens:
                    continue

                title_unique = set(title_tokens)
                overlap = len(target_unique.intersection(title_unique))
                if overlap < 2:
                    continue

                recall = float(overlap) / float(len(target_unique))
                precision = float(overlap) / float(len(title_unique))
                if recall < 0.75 or precision < 0.6:
                    continue

                f1_score = (2.0 * precision * recall) / (precision + recall)

                title_type = (title.get('type') or '').lower()
                type_rank = 2 if title_type == 'main' else (1 if title_type == 'official' else 0)
                token_len_penalty = -abs(len(title_unique) - len(target_unique))
                candidate = (f1_score, overlap, type_rank, token_len_penalty, aid)

                if best_match is None or candidate > best_match:
                    best_match = candidate

        if best_match is not None:
            return best_match[4]
    except Exception:
        return 0

    return 0


def set_up_anidb_connection():
    """Connect to anidb."""
    if not app.USE_ANIDB:
        log.debug(u'Usage of anidb disabled. Skipping')
        return False

    if not app.ANIDB_USERNAME and not app.ANIDB_PASSWORD:
        log.debug(u'anidb username and/or password are not set.'
                  u' Aborting anidb lookup.')
        return False

    if not app.ADBA_CONNECTION:
        try:
            app.ADBA_CONNECTION = adba.Connection(keepAlive=True)
        except Exception as error:
            log.warning(u'anidb exception msg: {0!r}', error)
            return False

    try:
        if not app.ADBA_CONNECTION.authed():
            app.ADBA_CONNECTION.auth(app.ANIDB_USERNAME, app.ANIDB_PASSWORD)
        else:
            return True
    except Exception as error:
        log.warning(u'anidb exception msg: {0!r}', error)
        return False

    return app.ADBA_CONNECTION.authed()


@anidb_cache.cache_on_arguments(namespace='anidb_releasegroups_v3', function_key_generator=create_key)
def get_release_groups_for_anime(series_name):
    """Get release groups for an anidb anime."""
    groups = []
    if set_up_anidb_connection():
        try:
            cache_path = join(app.CACHE_DIR, 'adba')
            anime = adba.Anime(
                app.ADBA_CONNECTION,
                name=series_name,
                autoCorrectName=True,
                cache_path=cache_path
            )

            # If the local AniDB title XML does not contain this title yet, ask AniDB by name first.
            # load_data() can populate anime.aid from the live ANIME response, enabling groupstatus lookups.
            if not anime.aid:
                try:
                    anime.load_data()
                except Exception:
                    pass

            # Fallback for strict/failed name resolution.
            if not anime.aid:
                aid = _get_aid_from_xml_loose(series_name, cache_path)
                if aid:
                    log.debug(u'Using AniDB XML fallback aid={aid} for {name}', {'aid': aid, 'name': series_name})
                    anime = adba.Anime(
                        app.ADBA_CONNECTION,
                        aid=aid,
                        cache_path=cache_path
                    )

            groups = anime.get_groups()
        except Exception as error:
            log.warning(u'Unable to retrieve Fansub Groups from AniDB. Error: {error!r}', {'error': error})
            raise AnidbAdbaConnectionException(error)

    return groups


def _get_release_groups_for_anime_aid_uncached(aid, force_reauth=False):
    """Get release groups for an anime by explicit AniDB AID without cache."""
    groups = []
    if not aid:
        return groups

    if force_reauth:
        try:
            app.ADBA_CONNECTION = None
        except Exception:
            pass

    if set_up_anidb_connection():
        try:
            cache_path = join(app.CACHE_DIR, 'adba')
            anime = adba.Anime(
                app.ADBA_CONNECTION,
                aid=int(aid),
                cache_path=cache_path
            )
            groups = anime.get_groups()
        except Exception as error:
            log.warning(u'Unable to retrieve Fansub Groups from AniDB by aid. Error: {error!r}', {'error': error})
            raise AnidbAdbaConnectionException(error)

    return groups


@anidb_cache.cache_on_arguments(namespace='anidb_releasegroups_aid_v2', function_key_generator=create_key)
def _get_release_groups_for_anime_aid_cached(aid):
    """Cached AniDB AID lookup.

    Note: empty lists can be caused by transient AniDB auth/session issues,
    so callers should verify empty cache hits with a forced uncached retry.
    """
    return _get_release_groups_for_anime_aid_uncached(aid)


def get_release_groups_for_anime_aid(aid):
    """Get release groups for an anime by explicit AniDB AID."""
    groups = _get_release_groups_for_anime_aid_cached(aid)

    # Guard against stale or transient empty cache entries (e.g. AniDB 501 LOGIN FIRST).
    if not groups and aid:
        try:
            groups = _get_release_groups_for_anime_aid_uncached(aid, force_reauth=True)
        except AnidbAdbaConnectionException:
            raise
        except Exception as error:
            log.warning(u'Unable to retrieve Fansub Groups from AniDB by aid retry. Error: {error!r}', {'error': error})
            raise AnidbAdbaConnectionException(error)

    return groups


@anidb_cache.cache_on_arguments(namespace='anidb', function_key_generator=create_key)
def get_short_group_name(release_group):
    short_group_list = []

    try:
        group = app.ADBA_CONNECTION.group(gname=release_group)
    except AniDBCommandTimeoutError:
        log.debug('Timeout while loading group from AniDB. Trying next group')
    except Exception:
        log.debug('Failed while loading group from AniDB. Trying next group')
    else:
        for line in group.datalines:
            if line['shortname']:
                short_group_list.append(line['shortname'])
            else:
                if release_group not in short_group_list:
                    short_group_list.append(release_group)

    return short_group_list


def short_group_names(groups):
    """Find AniDB short group names for release groups.

    :param groups: list of groups to find short group names for
    :return: list of shortened group names
    """
    short_group_list = []
    if set_up_anidb_connection():
        for group_name in groups:
            # Try to get a short group name, or return the group name provided.
            short_group_list += get_short_group_name(group_name) or [group_name]
    else:
        short_group_list = groups
    return short_group_list
