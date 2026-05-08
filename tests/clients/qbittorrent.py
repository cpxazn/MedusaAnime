# coding=utf-8

import json
import os
from types import SimpleNamespace

from medusa.clients.torrent.qbittorrent import QBittorrentAPI

import pytest


def test_torrent_completed(monkeypatch):
    # Given
    expected = True

    monkeypatch.setattr(QBittorrentAPI, '_get_auth', lambda self: True)

    # When
    client = QBittorrentAPI(host='http://localhost')
    client.api = (2, 0, 0)
    client.auth = True
    monkeypatch.setattr(client, '_torrent_properties', lambda info_hash: {
        'state': 'uploading',
        'ratio': 1.0,
        'downloaded': 1,
        'size': 1,
        'save_path': '/tmp',
    })

    actual = client.torrent_completed('aabbcc')

    # Then
    assert expected == actual


@pytest.mark.parametrize('state, expected', [
    ('stoppedDL', 'Paused'),
    ('stoppedUP', 'Completed'),
])
def test_get_status_maps_qbittorrent_5_states(monkeypatch, state, expected):
    monkeypatch.setattr(QBittorrentAPI, '_get_auth', lambda self: True)

    client = QBittorrentAPI(host='http://localhost')
    client.api = (2, 0, 0)
    client.auth = True

    monkeypatch.setattr(client, '_torrent_properties', lambda info_hash: {
        'state': state,
        'ratio': 0.0,
        'downloaded': 0,
        'size': 1,
        'save_path': '/tmp',
    })

    actual = client.get_status('aabbcc')

    assert expected == str(actual)


def test_get_auth_v2_accepts_empty_204_response(monkeypatch):
    client = QBittorrentAPI.__new__(QBittorrentAPI)
    client.name = 'qBittorrent'
    client.host = 'http://localhost'
    client.username = 'user'
    client.password = 'pass'
    client.session = SimpleNamespace(post=lambda *args, **kwargs: SimpleNamespace(
        status_code=204,
        text='',
        cookies={}
    ))

    monkeypatch.setattr(QBittorrentAPI, '_get_auth_legacy', lambda self: None)

    actual = QBittorrentAPI._get_auth_v2(client)

    assert actual is True
    assert client.auth is True
