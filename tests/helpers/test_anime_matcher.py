# coding=utf-8
"""Regression tests for confirmed identity and title suggestions."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from medusa import app
from medusa.clients.anime import AnimeSeries
from medusa.helpers.anime_matcher import find_similar_anime, match_anime_to_show
from medusa.indexers.config import INDEXER_TVDBV2


def _anime(title=None, **fields):
    return AnimeSeries(anime_id=1, source='livechart', title_english=title, **fields)


def _show(title, series_id=12, start_year=None, is_anime=True):
    return SimpleNamespace(indexer=INDEXER_TVDBV2, indexerid=series_id, series_id=series_id, title=title, name=title,
                           start_year=start_year, is_anime=is_anime)


@pytest.mark.parametrize(('title', 'owned'), [
    ('Black Clover', 'Black Summoner'),
    ('Overgeared', 'Overlord'),
    ('Black', 'Black Summoner'),
    ('The', 'The Twelve Kingdoms'),
    ('A', 'A Silent Voice'),
    ('Black Summoner', 'Live Black Clover'),
    ('Naruto', 'One Piece'),
])
def test_collisions_are_neither_owned_nor_suggested(title, owned):
    with patch.object(app, 'showList', [_show(owned)]):
        assert match_anime_to_show(_anime(title)) is None
        assert find_similar_anime(_anime(title)) == []


@pytest.mark.parametrize(('title', 'owned'), [
    ('Black Clover', 'Black Clover'),
    ('  black clover ', 'Black Clover'),
    ('Black Clover: Special', 'Black Clover - Special'),
    ('Ｆａｔｅ', 'ＦＡＴＥ'),
    ('葬送のフリーレン', '葬送のフリーレン'),
])
def test_exact_match_returns_one(title, owned):
    show = _show(owned)
    with patch.object(app, 'showList', [show]):
        assert match_anime_to_show(_anime(title)) is show
        assert find_similar_anime(_anime(title)) == [(show, 1.0)]


@pytest.mark.parametrize(('short', 'long'), [
    ('Frieren', "Frieren: Beyond Journey's End"),
    ('Black Clover Season 2', 'Black Clover'),
])
def test_unconfirmed_abbreviations_or_sequels_are_suggestions_only(short, long):
    show = _show(long)
    with patch.object(app, 'showList', [show]):
        assert match_anime_to_show(_anime(short)) is None
        assert find_similar_anime(_anime(short)) == [(show, 0.85)]


def test_catalogue_alias_can_confirm_abbreviation():
    full_title = "Frieren: Beyond Journey's End"
    show = _show(full_title)
    with patch.object(app, 'showList', [show]):
        assert match_anime_to_show(_anime('Frieren', title_synonyms=[full_title])) is show


@pytest.mark.parametrize('season, confirmed', [(-1, True), (2, False)])
def test_only_whole_series_aliases_confirm_identity(season, confirmed):
    show = _show("Frieren: Beyond Journey's End")
    aliases = {season: [SimpleNamespace(title='Frieren')]}
    with patch.object(app, 'showList', [show]), patch('medusa.helpers.anime_matcher.get_all_scene_exceptions',
                                                    return_value=aliases):
        assert match_anime_to_show(_anime('Frieren')) is (show if confirmed else None)


def test_sequels_need_same_tvdb_identity_and_ignore_year_when_mapped():
    show = _show('Black Clover', start_year=2017, is_anime=False)
    with patch.object(app, 'showList', [show]):
        assert match_anime_to_show(_anime('Black Clover Season 2', tvdb_id=12, year=2026)) is show
        assert match_anime_to_show(_anime('Black Clover', tvdb_id=13)) is None


def test_anidb_cross_reference_confirms_owned_series():
    show = _show('Black Clover')
    with patch.object(app, 'showList', [show]), patch('medusa.helpers.anime_matcher.cached_aid_to_tvdb',
                                                    return_value=12) as lookup:
        assert match_anime_to_show(_anime('Black Clover Season 2', anidb_id=23)) is show
        lookup.assert_called_once_with(23)


def test_exact_title_does_not_pick_remake_without_year():
    first = _show('Same Title', start_year=2011)
    second = _show('Same Title', series_id=13, start_year=2026)
    with patch.object(app, 'showList', [first, second]):
        assert match_anime_to_show(_anime('Same Title')) is None
        assert match_anime_to_show(_anime('Same Title', year=2026)) is second


def test_suggestion_order_and_limit():
    exact = _show('Frieren')
    long = _show("Frieren: Beyond Journey's End", series_id=13)
    with patch.object(app, 'showList', [long, exact]):
        assert find_similar_anime(_anime('Frieren'), 1) == [(exact, 1.0)]
        assert find_similar_anime(_anime()) == []
