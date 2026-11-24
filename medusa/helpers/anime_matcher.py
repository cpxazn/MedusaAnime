# coding=utf-8
"""Resolve anime library identity separately from title suggestions."""
from __future__ import unicode_literals

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from medusa.clients.anime import AnimeSeries
from medusa.indexers.config import INDEXER_TVDBV2
from medusa.logger.adapters.style import BraceAdapter
from medusa.scene_exceptions import get_all_scene_exceptions
from medusa.show.recommendations.recommended import cached_aid_to_tvdb
from medusa.tv.series import Series, SeriesIdentifier

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())

_GENERIC_TOKENS = frozenset(('a', 'an', 'and', 'black', 'of', 'the', 'to'))


def title_tokens(title):
    """Normalize case and punctuation without losing Unicode word boundaries."""
    return tuple(re.findall(r'[^\W_]+', unicodedata.normalize('NFC', title or '').casefold()))


def anime_titles(anime):
    """Return the catalogue's titles and aliases, not generated abbreviations."""
    return (anime.title_english, anime.title_romanji, anime.title_japanese,
            anime.display_title, *(anime.title_synonyms or ()))


def mapped_tvdb_id(anime):
    """Use a catalogue TVDB ID or existing AniDB cross-reference."""
    if anime.tvdb_id:
        return anime.tvdb_id
    if anime.anidb_id:
        try:
            return cached_aid_to_tvdb(anime.anidb_id)
        except Exception as error:
            log.debug('AniDB mapping failed for ID {aid}: {error}', aid=anime.anidb_id, error=error)
    return None


def find_owned_tvdb_series(tvdb_id):
    """Find a library series by its TVDB identity, including non-anime entries."""
    return Series.find_by_identifier(SeriesIdentifier(INDEXER_TVDBV2, int(tvdb_id)))


class AnimeMatcher:
    """Find confirmed library entries or separately rank possible suggestions."""

    @staticmethod
    def exact_title_matches(anime: AnimeSeries) -> List[Series]:
        """Find exact catalogue titles or whole-series aliases, without picking ties."""
        titles = {tokens for title in anime_titles(anime) if (tokens := title_tokens(title))}
        if not titles:
            return []
        matches = []
        for show in Series.find_series(predicate=lambda s: s.is_anime):
            # Mapped sequels bypass this comparison and are looked up by ID.
            if anime.year and show.start_year and anime.year != show.start_year:
                continue
            aliases = get_all_scene_exceptions(show).get(-1, ())
            names = (show.title, show.name, *(alias.title for alias in aliases))
            if any(title_tokens(name) in titles for name in names):
                matches.append(show)
        return matches

    def match_anime_to_show(self, anime: AnimeSeries) -> Optional[Series]:
        """Match by ID, or absent an ID, by a unique exact title or series alias."""
        tvdb_id = mapped_tvdb_id(anime)
        if tvdb_id:
            # An ID that is not owned is not a reason to fall back to a title.
            return find_owned_tvdb_series(tvdb_id)
        matches = self.exact_title_matches(anime)
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _suggestion_score(first, second):
        """Score exact titles, whole-token prefixes and close token-aware spellings."""
        left, right = title_tokens(first), title_tokens(second)
        if not left or not right:
            return 0.0
        if left == right:
            return 1.0
        short, long = sorted((left, right), key=len)
        if long[:len(short)] == short and set(short) - _GENERIC_TOKENS:
            return 0.85
        shared = (set(left) & set(right)) - _GENERIC_TOKENS
        if shared:
            ratio = SequenceMatcher(None, ' '.join(left), ' '.join(right), autojunk=False).ratio()
            if ratio >= 0.90:
                return ratio
        return 0.0

    def find_similar_shows(self, anime: AnimeSeries, limit: int = 10) -> List[Tuple[Series, float]]:
        """Rank suggestions only; the score never establishes library identity."""
        matches = []
        for show in Series.find_series(predicate=lambda s: s.is_anime):
            score = max(self._suggestion_score(title, show.title) for title in anime_titles(anime))
            if score:
                matches.append((show, score))
        return sorted(matches, key=lambda match: -match[1])[:limit]


def match_anime_to_show(anime: AnimeSeries) -> Optional[Series]:
    """Return a confirmed library match, never a fuzzy suggestion."""
    return AnimeMatcher().match_anime_to_show(anime)


def find_similar_anime(anime: AnimeSeries, limit: int = 10) -> List[Tuple[Series, float]]:
    """Return ranked library suggestions for an anime."""
    return AnimeMatcher().find_similar_shows(anime, limit)
