# coding=utf-8
"""Exercise Medusa's actual anime matcher through the HTTP API."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from medusa import app
from medusa.clients.anime import AnimeSeries
from medusa.indexers.config import INDEXER_TVDBV2
from medusa.queues.show_queue import QueueItemAdd
from medusa.server.api.v2 import anime as anime_api
from medusa.tv.series import SeriesIdentifier


def _owned(title, tvdb_id, year=None):
    return SimpleNamespace(name=title, title=title, is_anime=True, start_year=year,
                           indexer=INDEXER_TVDBV2, series_id=tvdb_id, indexerid=tvdb_id,
                           identifier=SeriesIdentifier(INDEXER_TVDBV2, tvdb_id))


def _anime(anime_id, title, **fields):
    return AnimeSeries(anime_id=anime_id, source='myanimelist', title_english=title, **fields)


@pytest.fixture
def anime_backend(monkeypatch):
    owned = [_owned('Black Summoner', 101), _owned('Black Clover', 102, 2017),
             _owned('Overlord', 103), _owned("Frieren: Beyond Journey's End", 104)]
    catalogue = {
        1: _anime(1, 'Black Summoner', tvdb_id=101),
        2: _anime(2, 'Black Clover', tvdb_id=201),  # same name; different resolved series
        3: _anime(3, 'Overgeared', tvdb_id=203),
        4: _anime(4, 'Black Clover Season 2', anidb_id=42, year=2026),
        5: _anime(5, 'Black Clover Season 2', tvdb_id=205, year=2026),
        6: _anime(6, 'Frieren'),
        7: _anime(7, "Frieren: Beyond Journey's End", title_synonyms=['Frieren']),
        8: _anime(8, 'Unmapped Show'),
        9: _anime(9, 'Black Summoner: Origins', tvdb_id=209),
        10: _anime(10, 'Duplicate Catalogue Entry', tvdb_id=203),
    }
    client = SimpleNamespace(get_details=catalogue.__getitem__)
    tvdb = SimpleNamespace(search=MagicMock(return_value=[]))
    monkeypatch.setattr(anime_api, 'indexerApi', lambda indexer: SimpleNamespace(indexer=lambda: tvdb, api_params={}))
    monkeypatch.setattr(anime_api.AnimeHandler, '_get_client', lambda handler, source: client)
    monkeypatch.setattr('medusa.helpers.anime_matcher.cached_aid_to_tvdb', lambda aid: {42: 102}.get(aid))
    monkeypatch.setattr(app, 'showList', owned)
    queue = SimpleNamespace(queue=[], current_item=None)

    def add_show(indexer, tvdb_id, show_dir, **options):
        item = QueueItemAdd.__new__(QueueItemAdd)
        item.indexer = indexer
        item.indexer_id = tvdb_id
        queue.queue.append(item)
        return SimpleNamespace(to_json={'queued': True})

    queue.addShow = MagicMock(side_effect=add_show)
    monkeypatch.setattr(app, 'show_queue_scheduler', SimpleNamespace(action=queue))
    return SimpleNamespace(owned=owned, tvdb=tvdb, queue=queue)


async def _post(http_client, create_url, endpoint, body):
    response = await http_client.fetch(create_url('/anime/' + endpoint), method='POST', body=json.dumps(body),
                                       headers={'Content-Type': 'application/json'}, raise_error=False)
    return response.code, json.loads(response.body)


@pytest.mark.gen_test
async def test_single_duplicate_only_for_confirmed_series(http_client, create_url, anime_backend):
    # An absent Black Clover must not be blocked by Black Summoner.
    anime_backend.owned.pop(1)
    code, body = await _post(http_client, create_url, 'add', {'anime_id': 2})
    assert (code, body) == (201, {'queued': True})
    code, body = await _post(http_client, create_url, 'add', {'anime_id': 1})
    assert code == 409
    assert body['outcome'] == 'already_exists'
    assert body['match'] == {'title': 'Black Summoner', 'slug': 'tvdb101'}
    code, body = await _post(http_client, create_url, 'add', {'anime_id': 6})
    assert code == 422
    assert body['outcome'] == 'needs_review'
    anime_backend.queue.addShow.assert_called_once()


@pytest.mark.gen_test
async def test_details_has_confirmed_ownership_and_canonical_title(http_client, create_url, anime_backend):
    for anime_id, expected in [(3, None), (4, ('Black Clover', 'tvdb102')), (5, None), (6, None)]:
        response = await http_client.fetch(create_url('/anime/details', id=anime_id, source='myanimelist'))
        body = json.loads(response.body)
        assert body['matched'] is bool(expected)
        if expected:
            assert body['match'] == dict(zip(('title', 'slug'), expected))


@pytest.mark.gen_test
async def test_bulk_dry_run_outcomes_and_write_rechecks_identity(http_client, create_url, anime_backend):
    request = {'items': [{'anime_id': n} for n in (2, 3, 4, 5, 6, 7, 8, 10)], 'identity_version': 1}
    code, body = await _post(http_client, create_url, 'bulk-add', dict(request, dry_run=True))
    assert code == 200
    assert body['identityVersion'] == 1
    assert [row['outcome'] for row in body['results']] == [
        'ready_to_add', 'ready_to_add', 'already_exists', 'ready_to_add', 'needs_review',
        'already_exists', 'mapping_failed', 'ready_to_add',
    ]
    assert body['results'][2]['match'] == {'title': 'Black Clover', 'slug': 'tvdb102'}
    assert body['results'][4]['candidates'][0]['slug'] == 'tvdb104'
    assert body['results'][5]['match']['slug'] == 'tvdb104'
    anime_backend.queue.addShow.assert_not_called()

    # Another actor registered this series after the dry-run.
    anime_backend.owned.append(_owned('Season 2', 205))
    code, body = await _post(http_client, create_url, 'bulk-add', dict(request, dry_run=False, verify=True))
    assert code == 200
    assert [row['outcome'] for row in body['results']] == [
        'queued', 'queued', 'already_exists', 'already_exists', 'needs_review',
        'already_exists', 'mapping_failed', 'already_queued',
    ]
    assert body['results'][1]['matched'] is False
    assert [call.args[1] for call in anime_backend.queue.addShow.call_args_list] == [201, 203]


@pytest.mark.gen_test
async def test_tvdb_fallback_uses_exact_alias_and_does_not_pick_between_ids(http_client, create_url, anime_backend):
    alias = {'id': '104', 'seriesname': "Frieren: Beyond Journey's End", 'aliases': 'Frieren'}
    anime_backend.tvdb.search.return_value = [alias, alias]
    body = {'items': [{'anime_id': 6}], 'dry_run': True}
    _, response = await _post(http_client, create_url, 'bulk-add', body)
    assert response['results'][0]['outcome'] == 'already_exists'
    anime_backend.tvdb.search.return_value.append({'id': 444, 'seriesname': 'Frieren'})
    _, response = await _post(http_client, create_url, 'bulk-add', body)
    result = response['results'][0]
    assert result['outcome'] == 'needs_review'
    assert result['matched'] is False
    assert {candidate['tvdbId'] for candidate in result['candidates']} == {104, 444}
