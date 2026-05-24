import base64
import json
import os

import bcrypt
import boto3
import pytest
from moto import mock_aws

os.environ['TABLE_NAME'] = 'DDNSAuthorization'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
os.environ['AWS_ACCESS_KEY_ID'] = 'test'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'

from src.authorizer import handler  # noqa: E402


def _make_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=4)).decode()


def _basic_auth(username: str, password: str) -> str:
    cred = base64.b64encode(f'{username}:{password}'.encode()).decode()
    return f'Basic {cred}'


def _event(username='testuser', password='testpass'):
    return {
        'headers': {'Authorization': _basic_auth(username, password)},
        'methodArn': 'arn:aws:execute-api:us-east-1:123456789:abc/prod/GET/nic/update',
    }


@pytest.fixture
def ddb_table():
    with mock_aws():
        client = boto3.client('dynamodb', region_name='us-east-1')
        client.create_table(
            TableName='DDNSAuthorization',
            KeySchema=[{'AttributeName': 'username', 'KeyType': 'HASH'}],
            AttributeDefinitions=[{'AttributeName': 'username', 'AttributeType': 'S'}],
            BillingMode='PAY_PER_REQUEST',
        )
        ddb = boto3.resource('dynamodb', region_name='us-east-1')
        table = ddb.Table('DDNSAuthorization')
        table.put_item(Item={
            'username': 'testuser',
            'password_hash': _make_hash('testpass'),
            'enabled': True,
            'allowed_hosts': [
                {'zone_id': 'Z0123456789ABCDEFGHIJ', 'hostname': 'test.example.com'},
            ],
        })
        yield table


def test_valid_credentials_returns_allow(ddb_table):
    resp = handler(_event(), None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Allow'
    assert resp['principalId'] == 'testuser'


def test_context_contains_allowed_hosts(ddb_table):
    resp = handler(_event(), None)
    hosts = json.loads(resp['context']['allowed_hosts'])
    assert len(hosts) == 1
    assert hosts[0]['hostname'] == 'test.example.com'
    assert hosts[0]['zone_id'] == 'Z0123456789ABCDEFGHIJ'


def test_wrong_password_returns_deny(ddb_table):
    resp = handler(_event(password='wrongpass'), None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Deny'


def test_unknown_user_returns_deny(ddb_table):
    resp = handler(_event(username='nobody'), None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Deny'


def test_disabled_user_returns_deny(ddb_table):
    ddb = boto3.resource('dynamodb', region_name='us-east-1')
    ddb.Table('DDNSAuthorization').put_item(Item={
        'username': 'disableduser',
        'password_hash': _make_hash('pass'),
        'enabled': False,
        'allowed_hosts': [],
    })
    resp = handler(_event(username='disableduser', password='pass'), None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Deny'


def test_missing_auth_header_returns_deny(ddb_table):
    event = {'headers': {}, 'methodArn': 'arn:aws:execute-api:us-east-1:123:x/p/GET/nic/update'}
    resp = handler(event, None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Deny'


def test_malformed_auth_not_basic(ddb_table):
    event = {
        'headers': {'Authorization': 'Bearer sometoken'},
        'methodArn': 'arn:aws:execute-api:us-east-1:123:x/p/GET/nic/update',
    }
    resp = handler(event, None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Deny'


def test_malformed_auth_no_colon(ddb_table):
    cred = base64.b64encode(b'nocolon').decode()
    event = {
        'headers': {'Authorization': f'Basic {cred}'},
        'methodArn': 'arn:aws:execute-api:us-east-1:123:x/p/GET/nic/update',
    }
    resp = handler(event, None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Deny'


def test_password_with_colon_works(ddb_table):
    # Passwords containing colons must work — only split on first colon
    ddb = boto3.resource('dynamodb', region_name='us-east-1')
    ddb.Table('DDNSAuthorization').put_item(Item={
        'username': 'colonuser',
        'password_hash': _make_hash('pass:word:with:colons'),
        'enabled': True,
        'allowed_hosts': [],
    })
    cred = base64.b64encode(b'colonuser:pass:word:with:colons').decode()
    event = {
        'headers': {'Authorization': f'Basic {cred}'},
        'methodArn': 'arn:aws:execute-api:us-east-1:123:x/p/GET/nic/update',
    }
    resp = handler(event, None)
    assert resp['policyDocument']['Statement'][0]['Effect'] == 'Allow'
