# coding=utf-8
"""Tests for medusa/server/api/v2/anime.py."""
from __future__ import unicode_literals

import json
from unittest.mock import MagicMock, patch

import pytest

from medusa.clients.anime import AnimeSeries
from medusa.server.api.v2.anime import AnimeHandler


def _make_anime(**kwargs):
    defaults = dict(anime_id=1, source='livechart')
    defaults.update(kwargs)
    return AnimeSeries(**defaults)


# ---------------------------------------------------------------------------
# GET /anime/search
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_search_missing_query(http_client, create_url):
    url = create_url('/anime/search')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400
    body = json.loads(response.body)
    assert 'q' in body['error'].lower() or 'query' in body['error'].lower()


@pytest.mark.gen_test
async def test_search_invalid_source(http_client, create_url):
    url = create_url('/anime/search', q='naruto', source='invalid_source')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400
    body = json.loads(response.body)
    assert 'source' in body['error'].lower() or 'invalid' in body['error'].lower()


@pytest.mark.gen_test
async def test_search_success(http_client, create_url, monkeypatch):
    anime = _make_anime(anime_id=1, title_english='Naruto', year=2002)
    mock_client = MagicMock()
    mock_client.search.return_value = [anime]

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url('/anime/search', q='naruto', source='livechart')
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert isinstance(data, list)
    assert len(data) == 1
    assert data[0]['animeId'] == 1
    assert data[0]['matched'] is False


@pytest.mark.gen_test
async def test_search_with_existing_match(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto', year=2002)
    mock_show = MagicMock()
    mock_show.title = 'Naruto'
    mock_show.identifier.slug = 'tvdb12345'
    mock_client = MagicMock()
    mock_client.search.return_value = [anime]

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=mock_show):
            url = create_url('/anime/search', q='naruto', source='livechart')
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert data[0]['matched'] is True
    assert data[0]['match']['slug'] == 'tvdb12345'


@pytest.mark.gen_test
async def test_search_client_error_returns_500(http_client, create_url):
    mock_client = MagicMock()
    mock_client.search.side_effect = RuntimeError('Connection failed')

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        url = create_url('/anime/search', q='naruto')
        response = await http_client.fetch(url, raise_error=False)

    assert response.code == 500


# ---------------------------------------------------------------------------
# GET /anime/seasonal
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_seasonal_missing_year(http_client, create_url):
    url = create_url('/anime/seasonal')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


@pytest.mark.gen_test
async def test_seasonal_invalid_source(http_client, create_url):
    url = create_url('/anime/seasonal', year=2026, season='spring', source='bad_source')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


@pytest.mark.gen_test
async def test_seasonal_success(http_client, create_url):
    animes = [_make_anime(anime_id=i, title_english=f'Show {i}', year=2026) for i in range(3)]
    mock_client = MagicMock()
    mock_client.get_seasonal.return_value = animes

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        url = create_url('/anime/seasonal', year=2026, season='SPRING', source='livechart')
        response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert len(data) == 3


# ---------------------------------------------------------------------------
# GET /anime/upcoming
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_upcoming_invalid_source(http_client, create_url):
    url = create_url('/anime/upcoming', source='unknown')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


@pytest.mark.gen_test
async def test_upcoming_success(http_client, create_url):
    animes = [_make_anime(anime_id=i, title_english=f'Upcoming {i}', year=2026) for i in range(5)]
    mock_client = MagicMock()
    mock_client.get_upcoming.return_value = animes

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        url = create_url('/anime/upcoming', source='livechart', limit=5)
        response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert len(data) == 5


# ---------------------------------------------------------------------------
# GET /anime/details
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_details_missing_id(http_client, create_url):
    url = create_url('/anime/details')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


@pytest.mark.gen_test
async def test_details_invalid_source(http_client, create_url):
    url = create_url('/anime/details', id=123, source='bad')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


@pytest.mark.gen_test
async def test_details_not_found(http_client, create_url):
    # anime_id of 0 / falsy means "not found"
    mock_client = MagicMock()
    mock_client.get_details.return_value = _make_anime(anime_id=0)

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        url = create_url('/anime/details', id=123)
        response = await http_client.fetch(url, raise_error=False)

    assert response.code == 404


@pytest.mark.gen_test
async def test_details_success(http_client, create_url):
    anime = _make_anime(anime_id=42, title_english='Naruto', year=2002)
    mock_client = MagicMock()
    mock_client.get_details.return_value = anime

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url('/anime/details', id=42)
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert data['animeId'] == 42
    assert data['matched'] is False


# ---------------------------------------------------------------------------
# GET /anime/match
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_match_invalid_source(http_client, create_url):
    url = create_url('/anime/match', id=1, source='bad')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


@pytest.mark.gen_test
async def test_match_success(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto')
    mock_show = MagicMock()
    mock_show.title = 'Naruto'
    mock_show.identifier.slug = 'tvdb12345'
    mock_client = MagicMock()
    mock_client.get_details.return_value = anime

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.find_similar_anime', return_value=[(mock_show, 0.95)]):
            url = create_url('/anime/match', id=1)
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert 'anime' in data
    assert 'matches' in data
    assert len(data['matches']) == 1
    assert data['matches'][0]['score'] == 0.95


# ---------------------------------------------------------------------------
# GET /anime/<invalid>
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_invalid_identifier_returns_400(http_client, create_url):
    url = create_url('/anime/unknownaction')
    response = await http_client.fetch(url, raise_error=False)
    assert response.code == 400


# ---------------------------------------------------------------------------
# POST /anime/add
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_add_invalid_identifier(http_client, create_url):
    url = create_url('/anime/notadd')
    body = json.dumps({})
    response = await http_client.fetch(
        url,
        method='POST',
        body=body,
        headers={'Content-Type': 'application/json'},
        raise_error=False,
    )
    assert response.code == 400


@pytest.mark.gen_test
async def test_add_missing_anime_id(http_client, create_url):
    url = create_url('/anime/add')
    body = json.dumps({'source': 'livechart'})
    response = await http_client.fetch(
        url,
        method='POST',
        body=body,
        headers={'Content-Type': 'application/json'},
        raise_error=False,
    )
    assert response.code == 400
    data = json.loads(response.body)
    assert 'anime_id' in data['error'].lower()


@pytest.mark.gen_test
async def test_add_invalid_source(http_client, create_url):
    url = create_url('/anime/add')
    body = json.dumps({'anime_id': 1, 'source': 'unknown_source'})
    response = await http_client.fetch(
        url,
        method='POST',
        body=body,
        headers={'Content-Type': 'application/json'},
        raise_error=False,
    )
    assert response.code == 400


@pytest.mark.gen_test
async def test_add_anime_already_in_library(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto', anidb_id=12345)
    mock_show = MagicMock()
    mock_show.title = 'Naruto'
    mock_client = MagicMock()
    mock_client.get_details.return_value = anime

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=mock_show):
            url = create_url('/anime/add')
            body = json.dumps({'anime_id': 1, 'source': 'livechart', 'root_dir': '/anime'})
            response = await http_client.fetch(
                url,
                method='POST',
                body=body,
                headers={'Content-Type': 'application/json'},
                raise_error=False,
            )

    assert response.code == 409


@pytest.mark.gen_test
async def test_add_anime_no_indexer_id(http_client, create_url):
    # anime without anidb_id and no TVDB mapping - should return 400
    anime = _make_anime(anime_id=1, title_english='Unknown Show')
    mock_client = MagicMock()
    mock_client.get_details.return_value = anime

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url('/anime/add')
            body = json.dumps({'anime_id': 1, 'source': 'livechart', 'root_dir': '/anime'})
            response = await http_client.fetch(
                url,
                method='POST',
                body=body,
                headers={'Content-Type': 'application/json'},
                raise_error=False,
            )

    assert response.code == 400
    data = json.loads(response.body)
    assert 'indexer' in data['error'].lower()


# ---------------------------------------------------------------------------
# Helper: _anime_to_json output shape
# ---------------------------------------------------------------------------

class TestAnimeToJson:
    """Tests for AnimeHandler._anime_to_json."""

    def setup_method(self):
        self.handler = AnimeHandler.__new__(AnimeHandler)

    def test_all_expected_keys_present(self):
        anime = _make_anime(
            anime_id=1,
            title_english='Test',
            title_romanji='Test Romanji',
            title_japanese='テスト',
            year=2021,
            genres=['Action'],
        )
        result = self.handler._anime_to_json(anime)
        expected_keys = {
            'animeId', 'source', 'titleJapanese', 'titleRomanji', 'titleEnglish',
            'titleSynonyms', 'synopsis', 'animeType', 'status', 'startDate', 'endDate',
            'season', 'year', 'episodes', 'episodeDurationMinutes', 'episodeInfo',
            'score', 'genres', 'tags', 'studios',
            'nextEpisodeNumber', 'nextEpisodeRelease', 'nextEpisodeCountdown', 'imageUrl',
            'anidbId', 'anilistId', 'tvdbId', 'malId', 'url', 'displayTitle', 'directoryName',
        }
        assert expected_keys == set(result.keys())

    def test_display_title_and_directory_name_populated(self):
        anime = _make_anime(anime_id=5, title_english='My Hero Academia', year=2016)
        result = self.handler._anime_to_json(anime)
        assert result['displayTitle'] == 'My Hero Academia'
        assert result['directoryName'] == 'My Hero Academia (2016)'

    def test_camel_case_keys(self):
        anime = _make_anime(anime_id=1, title_english='Test', anidb_id=999)
        result = self.handler._anime_to_json(anime)
        assert result['anidbId'] == 999
        assert result['animeId'] == 1
