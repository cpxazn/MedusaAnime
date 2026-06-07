# coding=utf-8
"""Test /show route."""
from __future__ import unicode_literals
import json
from unittest.mock import patch

import pytest


@pytest.mark.gen_test
async def test_show_get_no_series(http_client, create_url, auth_headers):
    # given
    url = create_url('/series')

    # when
    response = await http_client.fetch(url, **auth_headers)
    actual = json.loads(response.body)

    # then
    assert response.code == 200
    assert '1' == response.headers['X-Pagination-Page']
    assert '20' == response.headers['X-Pagination-Limit']
    assert '0' == response.headers['X-Pagination-Count']
    assert [] == actual


class FakeSeries(object):
    def __init__(self, title):
        self.title = title
        self.paused = False

    def to_json(self, detailed=False, episodes=False):
        return {'title': self.title}


@pytest.mark.gen_test
async def test_show_get_exact_page_does_not_advertise_next(http_client, create_url, auth_headers):
    url = create_url('/series')
    series = [FakeSeries('Show {0:02d}'.format(index)) for index in range(20)]

    with patch('medusa.server.api.v2.series.Series.find_series', return_value=series):
        response = await http_client.fetch(url, **auth_headers)

    actual = json.loads(response.body)

    assert response.code == 200
    assert '20' == response.headers['X-Pagination-Count']
    assert len(actual) == 20
    assert 'rel="next"' not in response.headers['Link']


@pytest.mark.gen_test
async def test_show_get_page_two_links_back_to_first_page(http_client, create_url, auth_headers):
    url = create_url('/series', page=2, limit=20)
    series = [FakeSeries('Show {0:02d}'.format(index)) for index in range(21)]

    with patch('medusa.server.api.v2.series.Series.find_series', return_value=series):
        response = await http_client.fetch(url, **auth_headers)

    actual = json.loads(response.body)

    assert response.code == 200
    assert '21' == response.headers['X-Pagination-Count']
    assert len(actual) == 1
    assert 'page=1&limit=20>; rel="first"' in response.headers['Link']
