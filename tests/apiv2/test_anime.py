# coding=utf-8
"""Tests for medusa/server/api/v2/anime.py."""
from __future__ import unicode_literals

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from medusa import app
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
async def test_search_passes_include_details_and_limit(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto', year=2002)
    mock_client = MagicMock()
    mock_client.search.return_value = [anime]

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url('/anime/search', q='naruto', source='livechart', includeDetails='true', limit=5)
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    mock_client.search.assert_called_once_with('naruto', include_details=True, limit=5)


@pytest.mark.gen_test
async def test_search_fields_projection(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto', year=2002, genres=['Action'])
    mock_client = MagicMock()
    mock_client.search.return_value = [anime]

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url('/anime/search', q='naruto', source='livechart', fields='animeId,titleEnglish,matched')
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert data == [{'animeId': 1, 'titleEnglish': 'Naruto', 'matched': False}]
    mock_client.search.assert_called_once_with('naruto', include_details=True, limit=20)


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
    assert isinstance(data, list)
    assert len(data) == 3


@pytest.mark.gen_test
async def test_seasonal_filters_before_pagination(http_client, create_url):
    animes = [
        _make_anime(anime_id=1, title_english='Kid Show', anime_type='TV', num_list_users=5000, genres=['Kids']),
        _make_anime(anime_id=2, title_english='Action Show', anime_type='TV', num_list_users=6000, genres=['Action']),
        _make_anime(anime_id=3, title_english='Movie Show', anime_type='Movie', num_list_users=7000, genres=['Action']),
        _make_anime(anime_id=4, title_english='Small Show', anime_type='TV', num_list_users=100, genres=['Action']),
    ]
    mock_client = MagicMock()
    mock_client.get_seasonal.return_value = animes

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url(
                '/anime/seasonal', year=2026, season='SPRING', source='livechart',
                animeType='tv', minNumListUsers=3000, excludeGenres='kids', limit=1,
            )
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert data['page'] == 1
    assert data['limit'] == 1
    assert data['total'] == 1
    assert data['hasNextPage'] is False
    assert [item['animeId'] for item in data['items']] == [2]
    assert data['items'][0]['matched'] is False


@pytest.mark.gen_test
async def test_seasonal_fields_projection_and_matched_filter(http_client, create_url):
    animes = [
        _make_anime(anime_id=1, title_english='Existing Show', anime_type='TV', num_list_users=5000),
        _make_anime(anime_id=2, title_english='New Show', anime_type='TV', num_list_users=6000),
    ]
    mock_show = MagicMock()
    mock_show.title = 'Existing Show'
    mock_show.identifier.slug = 'tvdb12345'
    mock_client = MagicMock()
    mock_client.get_seasonal.return_value = animes

    def match(anime):
        return mock_show if anime.anime_id == 1 else None

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', side_effect=match):
            url = create_url(
                '/anime/seasonal', year=2026, season='SPRING', source='livechart',
                matched='false', fields='animeId,titleEnglish,matched', limit=25,
            )
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert data == {
        'items': [{'animeId': 2, 'titleEnglish': 'New Show', 'matched': False}],
        'page': 1,
        'limit': 25,
        'total': 1,
        'hasNextPage': False,
    }


@pytest.mark.gen_test
async def test_seasonal_first_season_only_filter(http_client, create_url):
    animes = [
        _make_anime(anime_id=1, title_english='Brand New Show'),
        _make_anime(anime_id=2, title_english='Existing Show Season 2'),
        _make_anime(anime_id=3, title_english='Another Show', synopsis='A sequel to the original story.'),
    ]
    mock_client = MagicMock()
    mock_client.get_seasonal.return_value = animes

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            url = create_url('/anime/seasonal', year=2026, firstSeasonOnly='true')
            response = await http_client.fetch(url, raise_error=False)

    assert response.code == 200
    data = json.loads(response.body)
    assert [item['animeId'] for item in data['items']] == [1]


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


@pytest.mark.gen_test
async def test_add_anime_defaults_single_release_group_fallback(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto', anidb_id=12345)
    mock_client = MagicMock()
    mock_client.get_details.return_value = anime
    queue_item = MagicMock()
    queue_item.to_json = {'ok': True}

    original_groups = list(app.PREFERRED_ANIME_RELEASE_GROUPS)
    app.PREFERRED_ANIME_RELEASE_GROUPS = []
    scheduler = MagicMock()
    scheduler.action.addShow.return_value = queue_item

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            with patch('medusa.server.api.v2.anime.cached_aid_to_tvdb', return_value=None):
                with patch('medusa.indexers.utils.slug_to_indexer_id', return_value=666):
                    with patch.object(app, 'show_queue_scheduler', scheduler):
                        url = create_url('/anime/add')
                        body = json.dumps({'anime_id': 1, 'source': 'livechart', 'root_dir': '/anime'})
                        response = await http_client.fetch(
                            url,
                            method='POST',
                            body=body,
                            headers={'Content-Type': 'application/json'},
                            raise_error=False,
                        )

    app.PREFERRED_ANIME_RELEASE_GROUPS = original_groups

    assert response.code == 201
    _, kwargs = scheduler.action.addShow.call_args
    assert kwargs['whitelist'] == ['SubsPlease']
    assert kwargs['anime_release_group_fallback_groups'] == ['SubsPlease']
    assert kwargs['anime_release_group_fallback_days'] == 3


@pytest.mark.gen_test
async def test_add_anime_respects_initial_and_fallback_release_groups(http_client, create_url):
    anime = _make_anime(anime_id=1, title_english='Naruto', anidb_id=12345)
    mock_client = MagicMock()
    mock_client.get_details.return_value = anime
    queue_item = MagicMock()
    queue_item.to_json = {'ok': True}
    scheduler = MagicMock()
    scheduler.action.addShow.return_value = queue_item

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            with patch('medusa.server.api.v2.anime.cached_aid_to_tvdb', return_value=None):
                with patch('medusa.indexers.utils.slug_to_indexer_id', return_value=666):
                    with patch.object(app, 'show_queue_scheduler', scheduler):
                        url = create_url('/anime/add')
                        body = json.dumps({
                            'anime_id': 1,
                            'source': 'livechart',
                            'root_dir': '/anime',
                            'initial_release_group': 'SubsPlease',
                            'fallback_release_groups': ['Erai-raws', 'SubsPlease', 'Judas'],
                            'release_group_fallback_days': 5,
                        })
                        response = await http_client.fetch(
                            url,
                            method='POST',
                            body=body,
                            headers={'Content-Type': 'application/json'},
                            raise_error=False,
                        )

    assert response.code == 201
    _, kwargs = scheduler.action.addShow.call_args
    assert kwargs['whitelist'] == ['SubsPlease']
    assert kwargs['anime_release_group_fallback_groups'] == ['SubsPlease', 'Erai-raws', 'Judas']
    assert kwargs['anime_release_group_fallback_days'] == 5


# ---------------------------------------------------------------------------
# POST /anime/bulk-add
# ---------------------------------------------------------------------------

@pytest.mark.gen_test
async def test_bulk_add_dry_run_returns_per_item_results(http_client, create_url):
    animes = {
        1: _make_anime(anime_id=1, title_english='New Show', anidb_id=111, tvdb_id=222),
        2: _make_anime(anime_id=2, title_english='Existing Show', anidb_id=333, tvdb_id=444),
    }
    mock_show = MagicMock()
    mock_show.title = 'Existing Show'
    mock_show.identifier.slug = 'tvdb444'
    mock_client = MagicMock()
    mock_client.get_details.side_effect = lambda anime_id: animes[anime_id]
    scheduler = MagicMock()

    def match(anime):
        return mock_show if anime.anime_id == 2 else None

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', side_effect=match):
            with patch.object(app, 'show_queue_scheduler', scheduler):
                url = create_url('/anime/bulk-add')
                body = json.dumps({
                    'defaults': {
                        'source': 'livechart',
                        'root_dir': '/anime',
                        'status': 'wanted',
                        'initial_release_group': 'SubsPlease',
                    },
                    'items': [{'anime_id': 1}, {'anime_id': 2}],
                    'dry_run': True,
                    'verify': True,
                })
                response = await http_client.fetch(
                    url,
                    method='POST',
                    body=body,
                    headers={'Content-Type': 'application/json'},
                    raise_error=False,
                )

    assert response.code == 200
    data = json.loads(response.body)
    assert data['dryRun'] is True
    assert data['requested'] == 2
    assert data['successes'] == 1
    assert data['failures'] == 1
    assert data['results'][0]['animeId'] == 1
    assert data['results'][0]['success'] is True
    assert data['results'][0]['action'] == 'would_add'
    assert data['results'][0]['matched'] is False
    assert data['results'][1]['animeId'] == 2
    assert data['results'][1]['success'] is False
    assert data['results'][1]['action'] == 'already_exists'
    assert data['results'][1]['matched'] is True
    scheduler.action.addShow.assert_not_called()


@pytest.mark.gen_test
async def test_bulk_add_item_overrides_defaults_and_continues_after_failure(http_client, create_url):
    animes = {
        1: _make_anime(anime_id=1, title_english='New Show', anidb_id=111, tvdb_id=222),
        2: _make_anime(anime_id=0, title_english='Missing Show'),
    }
    mock_client = MagicMock()
    mock_client.get_details.side_effect = lambda anime_id: animes[anime_id]
    queue_item = MagicMock()
    queue_item.to_json = {'queued': True}
    scheduler = MagicMock()
    scheduler.action.addShow.return_value = queue_item

    with patch.object(AnimeHandler, '_get_client', return_value=mock_client):
        with patch('medusa.server.api.v2.anime.match_anime_to_show', return_value=None):
            with patch.object(app, 'show_queue_scheduler', scheduler):
                url = create_url('/anime/bulk-add')
                body = json.dumps({
                    'defaults': {
                        'source': 'livechart',
                        'root_dir': '/anime',
                        'initial_release_group': 'SubsPlease',
                        'fallback_release_groups': ['SubsPlease', 'Erai-raws'],
                    },
                    'items': [
                        {'anime_id': 1, 'directory_name': 'Custom Directory', 'initial_release_group': 'Erai-raws'},
                        {'anime_id': 2},
                    ],
                    'verify': True,
                })
                response = await http_client.fetch(
                    url,
                    method='POST',
                    body=body,
                    headers={'Content-Type': 'application/json'},
                    raise_error=False,
                )

    assert response.code == 200
    data = json.loads(response.body)
    assert data['requested'] == 2
    assert data['successes'] == 1
    assert data['failures'] == 1
    assert data['results'][0]['success'] is True
    assert data['results'][0]['action'] == 'added'
    assert data['results'][1]['success'] is False
    assert data['results'][1]['action'] == 'not_found'
    scheduler.action.addShow.assert_called_once()
    _, indexer_value, show_dir = scheduler.action.addShow.call_args[0]
    _, kwargs = scheduler.action.addShow.call_args
    assert indexer_value == 222
    assert show_dir == os.path.join('/anime', 'Custom Directory')
    assert kwargs['whitelist'] == ['Erai-raws']
    assert kwargs['anime_release_group_fallback_groups'] == ['Erai-raws', 'SubsPlease']


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
            'score', 'numListUsers', 'genres', 'tags', 'studios',
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
