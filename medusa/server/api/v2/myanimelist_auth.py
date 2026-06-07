# coding=utf-8
"""Request handler for MyAnimeList OAuth setup."""
from __future__ import unicode_literals

import logging
import secrets
import string
import time
from urllib.parse import urlencode

from medusa import app
from medusa.clients.myanimelist import MyAnimeListClient
from medusa.logger.adapters.style import BraceAdapter
from medusa.server.api.v2.base import BaseRequestHandler


log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())


class MyAnimeListAuthHandler(BaseRequestHandler):
    """Drive MyAnimeList OAuth from Medusa."""

    name = 'auth/myanimelist'
    identifier = ('identifier', r'\w+')
    allowed_methods = ('GET',)

    OAUTH_AUTHORIZE_URL = 'https://myanimelist.net/v1/oauth2/authorize'
    PKCE_ALPHABET = string.ascii_letters + string.digits + '-._~'
    STATE_TTL_SECONDS = 900

    def _check_authentication(self):
        """Allow MAL OAuth routes without API auth so callbacks can complete."""
        return None

    def get(self, identifier=None):
        """Start, inspect, or complete MyAnimeList OAuth setup."""
        if identifier == 'start':
            return self._start_oauth()
        if identifier in ('callback', 'complete'):
            return self._complete_oauth()
        if identifier == 'status':
            return self._status()
        return self._not_found()

    def _status(self):
        """Return current MAL OAuth state."""
        has_tokens = bool(app.MAL_ACCESS_TOKEN and app.MAL_REFRESH_TOKEN)
        pending = bool(app.MAL_OAUTH_STATE and app.MAL_OAUTH_CODE_VERIFIER)
        return self._ok({
            'enabled': bool(app.USE_MAL_API),
            'connected': has_tokens,
            'pending': pending,
            'clientIdConfigured': bool(app.MAL_CLIENT_ID),
            'clientSecretConfigured': bool(app.MAL_CLIENT_SECRET),
            'completionUrl': self._complete_url(),
            'callbackUrl': self._callback_url(),
        })

    def _start_oauth(self):
        """Redirect the browser to MAL's consent screen."""
        if not app.MAL_CLIENT_ID:
            return self._bad_request('MyAnimeList client ID is not configured')

        state = self._random_string(32)
        code_verifier = self._random_string(96)
        next_path = self.get_argument('next', default=None)
        if next_path and not next_path.startswith('/'):
            next_path = None

        app.MAL_OAUTH_STATE = state
        app.MAL_OAUTH_CODE_VERIFIER = code_verifier
        app.MAL_OAUTH_REDIRECT_URI = None
        app.MAL_OAUTH_NEXT_PATH = next_path
        app.MAL_OAUTH_STARTED_AT = int(time.time())

        params = {
            'response_type': 'code',
            'client_id': app.MAL_CLIENT_ID,
            'state': state,
            'code_challenge': code_verifier,
            'code_challenge_method': 'plain',
        }
        authorize_url = '{base}?{query}'.format(base=self.OAUTH_AUTHORIZE_URL, query=urlencode(params))
        return self._redirect_html(authorize_url, 'Connecting to MyAnimeList...')

    def _complete_oauth(self):
        """Handle MAL's callback and persist the returned tokens."""
        error = self.get_argument('error', default=None)
        if error:
            message = self.get_argument('message', default=error)
            return self._oauth_html(False, 'MyAnimeList authorization failed', message)

        code = self.get_argument('code', default=None)
        state = self.get_argument('state', default=None)
        if not code or not state:
            return self._oauth_html(False, 'Missing authorization response', 'MyAnimeList did not return the expected code and state.')

        if not self._pending_oauth_is_valid(state):
            return self._oauth_html(False, 'Authorization session expired', 'Start the MyAnimeList connection again from Medusa.')

        token_data = MyAnimeListClient.exchange_authorization_code(
            code=code,
            code_verifier=app.MAL_OAUTH_CODE_VERIFIER,
            redirect_uri=app.MAL_OAUTH_REDIRECT_URI,
        )
        if token_data is None or not MyAnimeListClient.apply_token_data(token_data):
            self._clear_pending_oauth()
            return self._oauth_html(False, 'Token exchange failed', 'Medusa could not save the MyAnimeList access token.')

        next_path = app.MAL_OAUTH_NEXT_PATH
        self._clear_pending_oauth()

        if next_path:
            separator = '&' if '?' in next_path else '?'
            return self._redirect_html(
                '{path}{separator}malAuth=success'.format(path=next_path, separator=separator),
                'Returning to Medusa...'
            )

        return self._oauth_html(True, 'MyAnimeList connected', 'Tokens were saved successfully. You can close this tab and return to Medusa.')

    def _pending_oauth_is_valid(self, state):
        """Validate the stored state/verifier pair."""
        started_at = app.MAL_OAUTH_STARTED_AT or 0
        if not (app.MAL_OAUTH_STATE and app.MAL_OAUTH_CODE_VERIFIER):
            return False
        if state != app.MAL_OAUTH_STATE:
            return False
        if int(time.time()) - int(started_at) > self.STATE_TTL_SECONDS:
            self._clear_pending_oauth()
            return False
        return True

    def _clear_pending_oauth(self):
        """Clear transient MAL OAuth handshake state."""
        app.MAL_OAUTH_STATE = None
        app.MAL_OAUTH_CODE_VERIFIER = None
        app.MAL_OAUTH_REDIRECT_URI = None
        app.MAL_OAUTH_NEXT_PATH = None
        app.MAL_OAUTH_STARTED_AT = None

    def _callback_url(self):
        """Build the absolute callback URL for this request."""
        protocol = self.request.headers.get('X-Forwarded-Proto', self.request.protocol)
        host = self.request.headers.get('X-Forwarded-Host', self.request.host)
        root = (app.WEB_ROOT or '').rstrip('/')
        return '{protocol}://{host}{root}/api/v2/auth/myanimelist/callback'.format(
            protocol=protocol,
            host=host,
            root=root,
        )

    def _complete_url(self):
        """Build the absolute completion URL for browser handoff flows."""
        protocol = self.request.headers.get('X-Forwarded-Proto', self.request.protocol)
        host = self.request.headers.get('X-Forwarded-Host', self.request.host)
        root = (app.WEB_ROOT or '').rstrip('/')
        return '{protocol}://{host}{root}/api/v2/auth/myanimelist/complete'.format(
            protocol=protocol,
            host=host,
            root=root,
        )

    def _oauth_html(self, success, title, message):
        """Render a lightweight browser-friendly OAuth result page."""
        status = 'Success' if success else 'Error'
        color = '#2b7a0b' if success else '#b42318'
        body = (
            '<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head>'
            '<body style="font-family:Arial,sans-serif;background:#f7f7f7;padding:32px;">'
            '<div style="max-width:680px;margin:0 auto;background:#fff;border:1px solid #ddd;border-radius:8px;padding:24px;">'
            '<h1 style="margin-top:0;color:{color};">{status}</h1>'
            '<h2 style="font-size:20px;margin-bottom:12px;">{title}</h2>'
            '<p style="font-size:14px;line-height:1.5;">{message}</p>'
            '</div></body></html>'
        ).format(status=status, title=title, message=message, color=color)
        return self.api_response(200, stream=body, content_type='text/html; charset=UTF-8')

    def _redirect_html(self, destination, title):
        """Render a browser redirect page without using Tornado's redirect API in a worker thread."""
        body = (
            '<!doctype html><html><head><meta charset="utf-8">'
            '<meta http-equiv="refresh" content="0; url={destination}">'
            '<title>{title}</title></head>'
            '<body style="font-family:Arial,sans-serif;background:#f7f7f7;padding:32px;">'
            '<div style="max-width:680px;margin:0 auto;background:#fff;border:1px solid #ddd;border-radius:8px;padding:24px;">'
            '<h1 style="margin-top:0;">{title}</h1>'
            '<p style="font-size:14px;line-height:1.5;">If you are not redirected automatically, '
            '<a href="{destination}">continue here</a>.</p>'
            '<script>window.location.replace({destination_js});</script>'
            '</div></body></html>'
        ).format(
            destination=destination,
            destination_js=repr(destination),
            title=title,
        )
        return self.api_response(200, stream=body, content_type='text/html; charset=UTF-8')

    @classmethod
    def _random_string(cls, length):
        return ''.join(secrets.choice(cls.PKCE_ALPHABET) for _ in range(length))
