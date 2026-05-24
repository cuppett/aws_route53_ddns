import base64
import json
import logging
import os

import bcrypt
import boto3

logging.getLogger().setLevel(os.environ.get('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

TABLE_NAME = os.environ.get('TABLE_NAME', 'DDNSAuthorization')


def _get_user(username: str) -> dict | None:
    ddb = boto3.resource('dynamodb')
    table = ddb.Table(TABLE_NAME)
    resp = table.get_item(Key={'username': username})
    return resp.get('Item')


def _parse_basic_auth(header: str) -> tuple[str, str] | None:
    if not header:
        return None
    parts = header.split(' ', 1)
    if len(parts) != 2 or parts[0].lower() != 'basic':
        return None
    try:
        decoded = base64.b64decode(parts[1]).decode('utf-8')
    except Exception:
        return None
    if ':' not in decoded:
        return None
    username, password = decoded.split(':', 1)
    return username, password


def _deny(principal='unauthorized'):
    return {
        'principalId': principal,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [{'Action': 'execute-api:Invoke', 'Effect': 'Deny', 'Resource': '*'}],
        },
    }


def _allow(principal: str, method_arn: str, allowed_hosts: list) -> dict:
    return {
        'principalId': principal,
        'policyDocument': {
            'Version': '2012-10-17',
            'Statement': [{'Action': 'execute-api:Invoke', 'Effect': 'Allow', 'Resource': method_arn}],
        },
        'context': {
            'username': principal,
            'allowed_hosts': json.dumps(allowed_hosts),
        },
    }


def handler(event, context):
    raw_headers = event.get('headers') or {}
    # API Gateway may lowercase header names; do a case-insensitive lookup
    headers_ci = {k.lower(): v for k, v in raw_headers.items()}
    auth_header = headers_ci.get('authorization', '')
    method_arn = event.get('methodArn', '*')

    credentials = _parse_basic_auth(auth_header)
    if not credentials:
        logger.warning('Missing or malformed Authorization header')
        return _deny()

    username, password = credentials
    user = _get_user(username)

    if not user:
        logger.warning('Unknown user: %s', username)
        return _deny(username)

    if not user.get('enabled', True):
        logger.warning('Disabled user: %s', username)
        return _deny(username)

    stored_hash = user.get('password_hash', '')
    try:
        valid = bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))
    except Exception:
        logger.exception('bcrypt error for user %s', username)
        return _deny(username)

    if not valid:
        logger.warning('Bad password for user: %s', username)
        return _deny(username)

    allowed_hosts = user.get('allowed_hosts', [])
    logger.info('Authorized: user=%s hosts=%d', username, len(allowed_hosts))
    return _allow(username, method_arn, allowed_hosts)
