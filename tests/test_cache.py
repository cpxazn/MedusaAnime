# coding=utf-8
from __future__ import unicode_literals

from medusa.providers.generic_provider import GenericProvider
from medusa.name_parser.parser import NameParser
from medusa.tv.cache import Cache


def test_update_cache_manual_search_reuses_parsed_result(monkeypatch, create_tvshow):
    release_name = '[Erai-raws].Kirio.Fan.Club.-.07.[720p.HIDIVE.WEB-DL.AVC.AAC][998A9FCC]'
    anime_series = create_tvshow(indexerid=123, name='Kirio Fan Club', anime=1)
    provider = GenericProvider('mock_provider')
    cache = Cache(provider)

    search_result = provider.get_result(series=anime_series)
    search_result.name = release_name
    search_result.url = 'https://example.test/kirio-fan-club-07'

    parsed_result = NameParser(parse_method='anime')._parse_string(release_name)
    parsed_result.series = anime_series
    search_result.parsed_result = parsed_result

    captured = {}

    class FakeDb(object):
        @staticmethod
        def mass_action(results):
            captured['results'] = results
            return results

    def fake_add_cache_entry(result, parsed_result=None):
        captured['release_group'] = parsed_result.release_group if parsed_result else None
        return ('INSERT', [parsed_result.release_group if parsed_result else None])

    monkeypatch.setattr(cache, '_clear_cache', lambda: None)
    monkeypatch.setattr(cache, '_get_db', lambda: FakeDb())
    monkeypatch.setattr(cache, 'add_cache_entry', fake_add_cache_entry)

    assert NameParser(parse_method='normal')._parse_string(release_name).release_group == 'HIDIVE'
    assert parsed_result.release_group == 'Erai-raws'

    cache.update_cache_manual_search([search_result])

    assert captured['release_group'] == 'Erai-raws'
    assert captured['results'] == [('INSERT', ['Erai-raws'])]
