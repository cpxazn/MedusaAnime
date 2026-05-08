# coding=utf-8
"""Tests for medusa/helpers/anidb.py."""
from __future__ import unicode_literals

from xml.etree import ElementTree

from medusa.helpers import anidb


def test_get_aid_from_xml_loose_rejects_weak_overlap(monkeypatch):
    """Loose fallback should avoid matching unrelated shows with token overlap."""
    xml_payload = """
    <animetitles>
      <anime aid="11480">
        <title type="main" xml:lang="x-jat">Netoge no Yome wa Onnanoko ja Nai to Omotta?</title>
      </anime>
      <anime aid="15131">
        <title type="main" xml:lang="x-jat">Maou Gakuin no Futekigousha</title>
      </anime>
    </animetitles>
    """

    monkeypatch.setattr(
        anidb,
        'read_anidb_xml',
        lambda _cache_path: ElementTree.fromstring(xml_payload)
    )

    aid = anidb._get_aid_from_xml_loose('Himekishi wa Barbaroi no Yome', 'unused')
    assert aid == 0


class _FakeAnime(object):
    """Simple fake for adba.Anime used to test release-group fallback behavior."""

    def __init__(self, _connection, name=None, aid=None, autoCorrectName=False, cache_path=None):
        self.name = name
        self.aid = aid or 0

    def load_data(self):
        if self.name == 'Himekishi wa Barbaroi no Yome':
            self.aid = 99999

    def get_groups(self):
        if self.aid == 99999:
            return [{'name': 'SampleGroup', 'rating': 100, 'range': '1-1'}]
        return []


def test_get_release_groups_for_anime_uses_name_lookup_before_xml_loose(monkeypatch):
    """When xml name mapping misses, live AniDB name lookup should still populate groups."""
    monkeypatch.setattr(anidb, 'set_up_anidb_connection', lambda: True)
    monkeypatch.setattr(anidb.app, 'ADBA_CONNECTION', object())
    monkeypatch.setattr(anidb.app, 'CACHE_DIR', 'd:/Medusa/.tmp_adba_cache')
    monkeypatch.setattr(anidb.adba, 'Anime', _FakeAnime)

    called = {'count': 0}

    def _fake_xml_loose(_series_name, _cache_path):
        called['count'] += 1
        return 0

    monkeypatch.setattr(anidb, '_get_aid_from_xml_loose', _fake_xml_loose)

    groups = anidb.get_release_groups_for_anime.__wrapped__('Himekishi wa Barbaroi no Yome')

    assert groups == [{'name': 'SampleGroup', 'rating': 100, 'range': '1-1'}]
    assert called['count'] == 0
