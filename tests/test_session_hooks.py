# coding=utf-8

from __future__ import unicode_literals

from medusa.session.hooks import _redact_post_body


def test_redact_post_body_masks_username_and_password():
    body = 'username=daniel&password=ylFiFw889lK3Pz&savepath=/downloads'

    actual = _redact_post_body(body, 'application/x-www-form-urlencoded')

    assert actual == 'username=**********&password=**********&savepath=%2Fdownloads'


def test_redact_post_body_keeps_non_sensitive_fields():
    body = 'category=anime&urls=https://example.com/torrent'

    actual = _redact_post_body(body, 'application/x-www-form-urlencoded')

    assert actual == 'category=anime&urls=https%3A%2F%2Fexample.com%2Ftorrent'