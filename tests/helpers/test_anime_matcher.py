# coding=utf-8
"""Tests for medusa/helpers/anime_matcher.py."""
from __future__ import unicode_literals

from collections import namedtuple

import pytest
from unittest.mock import MagicMock, patch

from medusa.clients.anime import AnimeSeries
from medusa.helpers.anime_matcher import AnimeMatcher, match_anime_to_show, find_similar_anime


# TitleException namedtuple matches the one in medusa/scene_exceptions.py
TitleException = namedtuple('TitleException', 'title, season, indexer, series_id, custom')


def _make_anime(**kwargs):
    defaults = dict(anime_id=1, source='livechart')
    defaults.update(kwargs)
    return AnimeSeries(**defaults)


def _make_show(series_id=12, indexer=1, title='Test Show', is_anime=True):
    show = MagicMock()
    show.series_id = series_id
    show.indexer = indexer
    show.title = title
    show.is_anime = is_anime
    show.identifier = MagicMock()
    show.identifier.slug = 'tvdb{0}'.format(series_id)
    return show


class TestFuzzyCompare:
    """Tests for AnimeMatcher._fuzzy_compare."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_exact_match_returns_one(self):
        assert self.matcher._fuzzy_compare('Tokyo Revengers', 'Tokyo Revengers') == 1.0

    def test_case_insensitive(self):
        assert self.matcher._fuzzy_compare('tokyo revengers', 'Tokyo Revengers') == 1.0

    def test_whitespace_stripped(self):
        assert self.matcher._fuzzy_compare('  Tokyo Revengers  ', 'Tokyo Revengers') == 1.0

    def test_empty_first_string_returns_zero(self):
        assert self.matcher._fuzzy_compare('', 'Tokyo Revengers') == 0.0

    def test_empty_second_string_returns_zero(self):
        assert self.matcher._fuzzy_compare('Tokyo Revengers', '') == 0.0

    def test_none_first_returns_zero(self):
        assert self.matcher._fuzzy_compare(None, 'Tokyo Revengers') == 0.0

    def test_none_second_returns_zero(self):
        assert self.matcher._fuzzy_compare('Tokyo Revengers', None) == 0.0

    def test_similar_strings_score_high(self):
        score = self.matcher._fuzzy_compare('Tokyo Revengers', 'Tokyo Revengers Season 2')
        assert score > 0.7

    def test_completely_different_strings_score_low(self):
        score = self.matcher._fuzzy_compare('Naruto', 'One Piece')
        assert score < 0.5


class TestCalculateMatchScore:
    """Tests for AnimeMatcher._calculate_match_score."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_exact_english_title_returns_one(self):
        anime = _make_anime(title_english='Attack on Titan')
        show = _make_show(title='Attack on Titan')
        score = self.matcher._calculate_match_score(anime, show)
        assert score == 1.0

    def test_english_weighted_higher_than_romanji(self):
        anime = _make_anime(title_english='Attack on Titan', title_romanji='Shingeki no Kyojin')
        show_en = _make_show(title='Attack on Titan')
        show_ro = _make_show(title='Shingeki no Kyojin')
        score_en = self.matcher._calculate_match_score(anime, show_en)
        score_ro = self.matcher._calculate_match_score(anime, show_ro)
        assert score_en >= score_ro

    def test_no_titles_returns_zero(self):
        anime = _make_anime()
        show = _make_show(title='Some Show')
        score = self.matcher._calculate_match_score(anime, show)
        assert score == 0

    def test_synonym_match_returns_positive_score(self):
        anime = _make_anime(title_synonyms=['AoT'])
        show = _make_show(title='AoT')
        score = self.matcher._calculate_match_score(anime, show)
        assert score > 0


class TestFindShowByException:
    """Tests for AnimeMatcher._find_show_by_exception."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_finds_show_by_series_id_and_indexer(self):
        exception = TitleException(
            title='Shingeki no Kyojin',
            season=-1,
            indexer=1,
            series_id=12,
            custom=False,
        )
        show = _make_show(series_id=12, indexer=1)

        with patch('medusa.helpers.anime_matcher.Series.find_series', return_value=[show]):
            result = self.matcher._find_show_by_exception(exception)
            assert result is show

    def test_returns_none_when_no_matching_show(self):
        exception = TitleException(
            title='Some Title',
            season=-1,
            indexer=1,
            series_id=999,
            custom=False,
        )

        with patch('medusa.helpers.anime_matcher.Series.find_series', return_value=[]):
            result = self.matcher._find_show_by_exception(exception)
            assert result is None

    def test_returns_none_on_exception(self):
        exception = TitleException(
            title='Some Title',
            season=-1,
            indexer=1,
            series_id=12,
            custom=False,
        )

        with patch('medusa.helpers.anime_matcher.Series.find_series', side_effect=RuntimeError('db error')):
            result = self.matcher._find_show_by_exception(exception)
            assert result is None


class TestMatchByRomanjiName:
    """Tests for AnimeMatcher._match_by_romanji_name."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_returns_none_when_no_romanji(self):
        anime = _make_anime(title_english='Attack on Titan')
        result = self.matcher._match_by_romanji_name(anime)
        assert result is None

    def test_matches_via_scene_exception(self):
        anime = _make_anime(title_romanji='Shingeki no Kyojin')
        exception = TitleException('Shingeki no Kyojin', -1, 1, 12, False)
        show = _make_show(series_id=12, indexer=1)

        with patch('medusa.helpers.anime_matcher.get_scene_exception_by_name', return_value=exception):
            with patch.object(self.matcher, '_find_show_by_exception', return_value=show):
                result = self.matcher._match_by_romanji_name(anime)
                assert result is show

    def test_returns_none_when_no_exception_found(self):
        anime = _make_anime(title_romanji='Some Unknown Title', title_japanese=None)

        with patch('medusa.helpers.anime_matcher.get_scene_exception_by_name', return_value=None):
            result = self.matcher._match_by_romanji_name(anime)
            assert result is None

    def test_falls_through_to_japanese_title(self):
        anime = _make_anime(title_romanji='Some Title', title_japanese='東京リベンジャーズ')
        exception = TitleException('東京リベンジャーズ', -1, 1, 12, False)
        show = _make_show(series_id=12, indexer=1)

        def fake_get_exception(name):
            if name == '東京リベンジャーズ':
                return exception
            return None

        with patch('medusa.helpers.anime_matcher.get_scene_exception_by_name', side_effect=fake_get_exception):
            with patch.object(self.matcher, '_find_show_by_exception', return_value=show):
                result = self.matcher._match_by_romanji_name(anime)
                assert result is show


class TestMatchByEnglishName:
    """Tests for AnimeMatcher._match_by_english_name."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_returns_none_when_no_english_title(self):
        anime = _make_anime(title_romanji='Shingeki no Kyojin')
        result = self.matcher._match_by_english_name(anime)
        assert result is None

    def test_delegates_to_search_by_name(self):
        anime = _make_anime(title_english='Attack on Titan')
        show = _make_show(title='Attack on Titan')

        with patch.object(self.matcher, '_search_by_name', return_value=show) as mock_search:
            result = self.matcher._match_by_english_name(anime)
            mock_search.assert_called_once_with('Attack on Titan')
            assert result is show


class TestMatchByByCrossReference:
    """Tests for AnimeMatcher._match_by_cross_reference."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_returns_none_when_no_anidb_id(self):
        anime = _make_anime()
        result = self.matcher._match_by_cross_reference(anime)
        assert result is None

    def test_matches_via_anidb_tvdb_mapping(self):
        anime = _make_anime(anidb_id=12345)
        show = _make_show(series_id=67890, indexer=1)
        mock_identifier = MagicMock()

        with patch('medusa.helpers.anime_matcher.cached_aid_to_tvdb', return_value=67890):
            with patch('medusa.helpers.anime_matcher.indexer_id_to_slug', return_value='tvdb67890'):
                with patch('medusa.helpers.anime_matcher.SeriesIdentifier.from_slug', return_value=mock_identifier):
                    with patch('medusa.helpers.anime_matcher.Series.find_by_identifier', return_value=show):
                        result = self.matcher._match_by_cross_reference(anime)
                        assert result is show

    def test_returns_none_when_no_tvdb_mapping(self):
        anime = _make_anime(anidb_id=12345)

        with patch('medusa.helpers.anime_matcher.cached_aid_to_tvdb', return_value=None):
            result = self.matcher._match_by_cross_reference(anime)
            assert result is None

    def test_returns_none_on_error(self):
        anime = _make_anime(anidb_id=12345)

        with patch('medusa.helpers.anime_matcher.cached_aid_to_tvdb', side_effect=Exception('API error')):
            result = self.matcher._match_by_cross_reference(anime)
            assert result is None


class TestFindSimilarShows:
    """Tests for AnimeMatcher.find_similar_shows."""

    def setup_method(self):
        self.matcher = AnimeMatcher()

    def test_returns_sorted_by_score_descending(self):
        anime = _make_anime(title_english='Attack on Titan')
        show_a = _make_show(series_id=1, title='Attack on Titan')
        show_b = _make_show(series_id=2, title='Attack on Titan: Season 2')

        with patch('medusa.helpers.anime_matcher.Series.find_series', return_value=[show_a, show_b]):
            results = self.matcher.find_similar_shows(anime)
            assert len(results) >= 1
            if len(results) > 1:
                assert results[0][1] >= results[1][1]

    def test_filters_below_min_similarity(self):
        anime = _make_anime(title_english='Naruto')
        show = _make_show(title='One Piece')  # Very different

        with patch('medusa.helpers.anime_matcher.Series.find_series', return_value=[show]):
            results = self.matcher.find_similar_shows(anime)
            assert len(results) == 0

    def test_respects_limit(self):
        anime = _make_anime(title_english='Attack on Titan')
        shows = [_make_show(series_id=i, title='Attack on Titan') for i in range(20)]

        with patch('medusa.helpers.anime_matcher.Series.find_series', return_value=shows):
            results = self.matcher.find_similar_shows(anime, limit=5)
            assert len(results) <= 5

    def test_empty_show_list_returns_empty(self):
        anime = _make_anime(title_english='Attack on Titan')

        with patch('medusa.helpers.anime_matcher.Series.find_series', return_value=[]):
            results = self.matcher.find_similar_shows(anime)
            assert results == []


class TestConvenienceFunctions:
    """Tests for module-level match_anime_to_show and find_similar_anime."""

    def test_match_anime_to_show_delegates_to_matcher(self):
        anime = _make_anime(title_english='Attack on Titan')
        show = _make_show(title='Attack on Titan')

        with patch.object(AnimeMatcher, 'match_anime_to_show', return_value=show) as mock:
            result = match_anime_to_show(anime)
            mock.assert_called_once_with(anime)
            assert result is show

    def test_find_similar_anime_delegates_to_matcher(self):
        anime = _make_anime(title_english='Attack on Titan')
        expected = [(_make_show(), 0.9)]

        with patch.object(AnimeMatcher, 'find_similar_shows', return_value=expected) as mock:
            result = find_similar_anime(anime, limit=5)
            mock.assert_called_once_with(anime, 5)
            assert result == expected
