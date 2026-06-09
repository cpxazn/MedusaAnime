# coding=utf-8
"""Tests for medusa.clients.myanimelist."""
from __future__ import unicode_literals

from unittest.mock import MagicMock

from medusa.clients.myanimelist import MyAnimeListClient


def test_search_api_maps_enriched_fields():
    client = MyAnimeListClient.__new__(MyAnimeListClient)
    client.use_official_api = True
    client._api_get = MagicMock(return_value={
        'data': [
            {
                'node': {
                    'id': 42,
                    'title': 'Naruto',
                    'alternative_titles': {
                        'en': 'Naruto English',
                        'ja': 'ナルト',
                        'synonyms': ['NARUTO'],
                    },
                    'main_picture': {'large': 'https://example.test/naruto.jpg'},
                    'start_date': '2002-10-03',
                    'synopsis': 'A ninja story.',
                    'mean': 7.99,
                    'num_list_users': 1000,
                    'media_type': 'tv',
                    'status': 'finished_airing',
                    'genres': [{'name': 'Action'}],
                    'num_episodes': 220,
                    'start_season': {'year': 2002, 'season': 'fall'},
                    'average_episode_duration': 1440,
                    'studios': [{'name': 'Pierrot'}],
                }
            }
        ]
    })

    results = client._search_api('naruto', limit=5)

    assert len(results) == 1
    anime = results[0]
    assert anime.anime_id == 42
    assert anime.mal_id == 42
    assert anime.title_english == 'Naruto English'
    assert anime.title_romanji == 'Naruto'
    assert anime.title_japanese == 'ナルト'
    assert anime.title_synonyms == ['NARUTO']
    assert anime.image_url == 'https://example.test/naruto.jpg'
    assert anime.year == 2002
    assert anime.season == 'FALL'
    assert anime.episodes == 220
    assert anime.episode_duration_minutes == 24
    assert anime.score == 7.99
    assert anime.num_list_users == 1000
    assert anime.anime_type == 'TV'
    assert anime.status == 'finished'
    assert anime.genres == ['Action']
    assert anime.studios == ['Pierrot']

    _, kwargs = client._api_get.call_args
    assert kwargs['params']['limit'] == 5
    assert 'alternative_titles' in kwargs['params']['fields']


def test_search_api_returns_none_when_official_api_disabled():
    client = MyAnimeListClient.__new__(MyAnimeListClient)
    client.use_official_api = False

    assert client._search_api('naruto') is None
