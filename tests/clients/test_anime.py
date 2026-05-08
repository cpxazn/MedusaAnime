# coding=utf-8
"""Tests for medusa/clients/anime/__init__.py."""
from __future__ import unicode_literals

import pytest

from medusa.clients.anime import AnimeSeries, AnimeSeason, AnimeSource


class TestAnimeSeries:
    """Tests for the AnimeSeries dataclass."""

    def test_display_title_prefers_english(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_english='Tokyo Revengers',
            title_romanji='Tokyo Revengers',
            title_japanese='東京リベンジャーズ',
        )
        assert anime.display_title == 'Tokyo Revengers'

    def test_display_title_falls_back_to_romanji(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_romanji='Tokyo Revengers',
            title_japanese='東京リベンジャーズ',
        )
        assert anime.display_title == 'Tokyo Revengers'

    def test_display_title_falls_back_to_japanese(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_japanese='東京リベンジャーズ',
        )
        assert anime.display_title == '東京リベンジャーズ'

    def test_display_title_falls_back_to_id(self):
        anime = AnimeSeries(anime_id=42, source='livechart')
        assert anime.display_title == 'Unknown Anime (42)'

    def test_directory_name_appends_year(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_romanji='Tokyo Revengers',
            year=2021,
        )
        assert anime.directory_name == 'Tokyo Revengers (2021)'

    def test_directory_name_no_year(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_romanji='Tokyo Revengers',
        )
        assert anime.directory_name == 'Tokyo Revengers'

    def test_directory_name_removes_invalid_chars(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_romanji='Fate/stay night: Unlimited Blade Works',
            year=2014,
        )
        name = anime.directory_name
        assert '/' not in name
        assert ':' not in name
        assert '2014' in name

    def test_directory_name_uses_english_when_no_romanji(self):
        anime = AnimeSeries(
            anime_id=1,
            source='livechart',
            title_english='Attack on Titan',
            year=2013,
        )
        assert anime.directory_name == 'Attack on Titan (2013)'

    def test_directory_name_falls_back_to_anime_id(self):
        anime = AnimeSeries(anime_id=99, source='livechart')
        assert anime.directory_name == 'anime_99'

    def test_start_year_returns_year(self):
        anime = AnimeSeries(anime_id=1, source='livechart', year=2021)
        assert anime.start_year == 2021

    def test_start_year_none_when_missing(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.start_year is None

    def test_default_status_is_upcoming(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.status == 'upcoming'

    def test_default_anime_type_is_tv(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.anime_type == 'TV'

    def test_cross_references_default_to_none(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.anidb_id is None
        assert anime.anilist_id is None
        assert anime.tvdb_id is None
        assert anime.mal_id is None

    def test_title_synonyms_default_to_empty_list(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.title_synonyms == []

    def test_genres_default_to_empty_list(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.genres == []

    def test_seasons_default_to_empty_list(self):
        anime = AnimeSeries(anime_id=1, source='livechart')
        assert anime.seasons == []


class TestAnimeSource:
    """Tests for the AnimeSource abstract base class."""

    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            AnimeSource()

    def test_concrete_subclass_must_implement_all_methods(self):
        class IncompleteSource(AnimeSource):
            def search(self, query):
                return []
            # Missing: get_seasonal, get_details, get_upcoming

        with pytest.raises(TypeError):
            IncompleteSource()

    def test_concrete_subclass_can_be_instantiated(self):
        class CompleteSource(AnimeSource):
            def search(self, query):
                return []

            def get_seasonal(self, year, season):
                return []

            def get_details(self, anime_id):
                return AnimeSeries(anime_id=anime_id, source='test')

            def get_upcoming(self, limit=20):
                return []

        source = CompleteSource()
        assert source is not None

    def test_concrete_subclass_search_returns_list(self):
        class TestSource(AnimeSource):
            def search(self, query):
                return [AnimeSeries(anime_id=1, source='test', title_english=query)]

            def get_seasonal(self, year, season):
                return []

            def get_details(self, anime_id):
                return AnimeSeries(anime_id=anime_id, source='test')

            def get_upcoming(self, limit=20):
                return []

        source = TestSource()
        results = source.search('naruto')
        assert len(results) == 1
        assert results[0].title_english == 'naruto'
