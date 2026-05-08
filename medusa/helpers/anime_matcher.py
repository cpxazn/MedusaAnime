# coding=utf-8
"""Anime name matching service."""
from __future__ import unicode_literals

import logging
import re
from difflib import SequenceMatcher
from typing import List, Optional, Tuple

from medusa import app
from medusa.clients.anime import AnimeSeries
from medusa.indexers.config import EXTERNAL_ANIDB, EXTERNAL_ANILIST, INDEXER_TVDBV2
from medusa.indexers.utils import indexer_id_to_slug
from medusa.logger.adapters.style import BraceAdapter
from medusa.scene_exceptions import get_scene_exception_by_name
from medusa.show.recommendations.recommended import (
    cached_aid_to_tvdb,
    cached_tvdb_to_aid,
)
from medusa.tv.series import Series, SeriesIdentifier

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class AnimeMatcher:
    """Service for matching anime titles across different databases."""

    def __init__(self):
        """Initialize the anime matcher."""
        self.min_similarity = 0.6  # Minimum similarity score for fuzzy matches
        self.high_confidence = 0.85  # Score for high-confidence matches

    def match_anime_to_show(self, anime: AnimeSeries) -> Optional[Series]:
        """Match an AnimeSeries to an existing Medusa show.
        
        Args:
            anime: AnimeSeries to match
            
        Returns:
            Series object if found, None otherwise
        """
        # Try matching strategies in order of confidence
        match = self._match_by_cross_reference(anime)
        if match:
            log.debug('Matched by cross-reference: {title}', title=anime.display_title)
            return match

        match = self._match_by_english_name(anime)
        if match:
            log.debug('Matched by English name: {title}', title=anime.display_title)
            return match

        match = self._match_by_romanji_name(anime)
        if match:
            log.debug('Matched by Romanji name: {title}', title=anime.display_title)
            return match

        match = self._match_by_synonyms(anime)
        if match:
            log.debug('Matched by synonyms: {title}', title=anime.display_title)
            return match

        match = self._match_fuzzy(anime)
        if match:
            log.debug('Matched by fuzzy matching: {title}', title=anime.display_title)
            return match

        return None

    def find_similar_shows(self, anime: AnimeSeries, limit: int = 10) -> List[Tuple[Series, float]]:
        """Find shows similar to the given anime.
        
        Args:
            anime: AnimeSeries to find matches for
            limit: Maximum number of results
            
        Returns:
            List of (Series, confidence_score) tuples
        """
        matches = []
        
        # Get all shows in the library (anime shows specifically)
        all_shows = Series.find_series(predicate=lambda s: s.is_anime)
        
        for show in all_shows:
            score = self._calculate_match_score(anime, show)
            if score >= self.min_similarity:
                matches.append((show, score))
        
        # Sort by score descending and return top N
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[:limit]

    def _match_by_cross_reference(self, anime: AnimeSeries) -> Optional[Series]:
        """Try to match using cross-references (AniDB, AniList IDs)."""
        # Try AniDB ID mapping
        if anime.anidb_id:
            try:
                tvdb_id = cached_aid_to_tvdb(anime.anidb_id)
                if tvdb_id:
                    # Load show by TVDB ID
                    slug = indexer_id_to_slug(INDEXER_TVDBV2, tvdb_id)
                    if slug:
                        identifier = SeriesIdentifier.from_slug(slug)
                        if identifier:
                            show = Series.find_by_identifier(identifier)
                            if show:
                                return show
            except Exception as error:
                log.debug('AniDB mapping failed for ID {aid}: {error}', aid=anime.anidb_id, error=error)

        # Try AniList ID mapping
        if anime.anilist_id:
            # AniList doesn't have a direct cache like AniDB
            # We'll need to search by name as fallback
            pass

        return None

    def _match_by_english_name(self, anime: AnimeSeries) -> Optional[Series]:
        """Try to match using English title."""
        if not anime.title_english:
            return None

        return self._search_by_name(anime.title_english)

    def _match_by_romanji_name(self, anime: AnimeSeries) -> Optional[Series]:
        """Try to match using Romanji title via scene exceptions."""
        if not anime.title_romanji:
            return None

        # Search scene exceptions for Romanji matches
        try:
            exception = get_scene_exception_by_name(anime.title_romanji)
            if exception:
                show = self._find_show_by_exception(exception)
                if show:
                    return show
        except Exception as error:
            log.debug('Scene exception search failed: {error}', error=error)

        # Also try Japanese title
        if anime.title_japanese:
            try:
                exception = get_scene_exception_by_name(anime.title_japanese)
                if exception:
                    show = self._find_show_by_exception(exception)
                    if show:
                        return show
            except Exception:
                pass

        return None

    def _match_by_synonyms(self, anime: AnimeSeries) -> Optional[Series]:
        """Try to match using alternative titles/synonyms."""
        for synonym in anime.title_synonyms:
            show = self._search_by_name(synonym)
            if show:
                return show

        return None

    def _match_fuzzy(self, anime: AnimeSeries) -> Optional[Series]:
        """Try fuzzy matching against all shows."""
        if not anime.display_title:
            return None

        all_shows = Series.find_series(predicate=lambda s: s.is_anime)
        
        best_match = None
        best_score = 0

        for show in all_shows:
            score = self._fuzzy_compare(anime.display_title, show.title)
            if score > best_score:
                best_score = score
                best_match = show

        if best_match and best_score >= self.min_similarity:
            return best_match

        return None

    def _search_by_name(self, name: str) -> Optional[Series]:
        """Search for a show by name.
        
        Args:
            name: Show name to search for
            
        Returns:
            Series if found, None otherwise
        """
        try:
            # Use the scene exceptions system to find matches
            exception = get_scene_exception_by_name(name)
            if exception:
                show = self._find_show_by_exception(exception)
                if show:
                    return show
        except Exception as error:
            log.debug('Scene exception search failed: {error}', error=error)

        # Fallback: try direct title matching
        all_shows = Series.find_series(predicate=lambda s: s.is_anime)
        for show in all_shows:
            if self._fuzzy_compare(name, show.title) >= 0.9:
                return show

        return None

    def _find_show_by_exception(self, exception) -> Optional[Series]:
        """Find a show by scene exception (TitleException namedtuple).
        
        Args:
            exception: TitleException namedtuple with fields:
                       title, season, indexer, series_id, custom
            
        Returns:
            Series if found, None otherwise
        """
        try:
            shows = Series.find_series(
                predicate=lambda s: s.series_id == exception.series_id and s.indexer == exception.indexer
            )
            if shows:
                return shows[0]
        except Exception as error:
            log.debug('Failed to find show by exception: {error}', error=error)

        return None

    def _calculate_match_score(self, anime: AnimeSeries, show: Series) -> float:
        """Calculate a match score between an anime and a show.
        
        Args:
            anime: AnimeSeries to match
            show: Medusa show
            
        Returns:
            Similarity score (0-1)
        """
        scores = []
        
        # English title match
        if anime.title_english:
            score = self._fuzzy_compare(anime.title_english, show.title)
            scores.append(('english', score))
        
        # Romanji title match
        if anime.title_romanji:
            score = self._fuzzy_compare(anime.title_romanji, show.title)
            scores.append(('romanji', score))
        
        # Japanese title match (if show has scene exceptions with Japanese names)
        if anime.title_japanese:
            score = self._fuzzy_compare(anime.title_japanese, show.title)
            scores.append(('japanese', score))
        
        # Synonym matches
        for synonym in anime.title_synonyms:
            score = self._fuzzy_compare(synonym, show.title)
            if score >= 0.7:
                scores.append(('synonym', score))
                break
        
        if not scores:
            return 0

        # Return the highest score with weighting
        weighted_scores = []
        for name_type, score in scores:
            if name_type == 'english':
                weighted_scores.append(score * 1.0)
            elif name_type == 'romanji':
                weighted_scores.append(score * 0.9)
            elif name_type == 'japanese':
                weighted_scores.append(score * 0.8)
            else:
                weighted_scores.append(score * 0.7)

        return max(weighted_scores)

    def _fuzzy_compare(self, str1: str, str2: str) -> float:
        """Calculate fuzzy similarity between two strings.
        
        Args:
            str1: First string
            str2: Second string
            
        Returns:
            Similarity score (0-1)
        """
        if not str1 or not str2:
            return 0.0

        str1 = str1.lower().strip()
        str2 = str2.lower().strip()

        # Exact match
        if str1 == str2:
            return 1.0

        # Use SequenceMatcher for fuzzy comparison
        return SequenceMatcher(None, str1, str2).ratio()


def match_anime_to_show(anime: AnimeSeries) -> Optional[Series]:
    """Convenience function to match an anime to a show.
    
    Args:
        anime: AnimeSeries to match
        
    Returns:
        Series if found, None otherwise
    """
    matcher = AnimeMatcher()
    return matcher.match_anime_to_show(anime)


def find_similar_anime(anime: AnimeSeries, limit: int = 10) -> List[Tuple[Series, float]]:
    """Convenience function to find similar shows.
    
    Args:
        anime: AnimeSeries to find matches for
        limit: Maximum number of results
        
    Returns:
        List of (Series, confidence_score) tuples
    """
    matcher = AnimeMatcher()
    return matcher.find_similar_shows(anime, limit)
