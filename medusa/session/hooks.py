# coding=utf-8

from __future__ import unicode_literals

import re
import logging

from medusa.logger.adapters.style import BraceAdapter

from six import ensure_text
from six.moves.urllib.parse import parse_qsl, quote_plus

log = BraceAdapter(logging.getLogger(__name__))
log.logger.addHandler(logging.NullHandler())

SENSITIVE_POST_FIELDS = {'password', 'pass', 'passwd', 'pwd', 'username'}


def _redact_post_body(body, content_type=None):
    """Mask sensitive form fields before logging POST data."""
    if not body:
        return body

    content_type = (content_type or '').lower()
    if 'application/x-www-form-urlencoded' in content_type or (
            'multipart/form-data' not in content_type and '&' in body and '=' in body):
        try:
            masked_pairs = []
            for key, value in parse_qsl(body, keep_blank_values=True):
                masked_value = '**********' if key.lower() in SENSITIVE_POST_FIELDS else value
                masked_pairs.append('{0}={1}'.format(
                    quote_plus(key),
                    quote_plus(masked_value, safe='*') if masked_value == '**********' else quote_plus(masked_value)
                ))

            return '&'.join(masked_pairs)
        except ValueError:
            pass

    redacted = body
    for field in SENSITIVE_POST_FIELDS:
        redacted = re.sub(
            r'(?i)({0}=)([^&\s]*)'.format(re.escape(field)),
            r'\1**********',
            redacted
        )

    return redacted


def log_url(response, **kwargs):
    """Response hook to log request URL."""
    request = response.request
    log.debug(
        '{method} URL: {url} [Status: {status}]', {
            'method': request.method,
            'url': request.url,
            'status': response.status_code,
        }
    )
    log.debug('User-Agent: {}'.format(request.headers['User-Agent']))

    if request.method.upper() == 'POST':
        if request.body:
            text_body = ensure_text(request.body, errors='replace')
            body = _redact_post_body(text_body, request.headers.get('content-type', ''))

            if 'multipart/form-data' in request.headers.get('content-type', ''):
                if len(body) > 99:
                    body = body[0:99].replace('\n', ' ') + '...'
                else:
                    body = body.replace('\n', ' ')

            log.debug('With post data: {0}', body)
