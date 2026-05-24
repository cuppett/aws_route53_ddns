import json
import os

import boto3
import pytest
from moto import mock_aws

os.environ['TABLE_NAME'] = 'DDNSAuthorization'
os.environ['RECORD_TTL'] = '60'
os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
os.environ['AWS_ACCESS_KEY_ID'] = 'test'
os.environ['AWS_SECRET_ACCESS_KEY'] = 'test'

from src.update_handler import handler  # noqa: E402

ZONE_ID = 'Z0123456789ABCDEFGHIJ'
HOSTNAME = 'test.example.com'
ALLOWED_HOSTS = json.dumps([{'zone_id': ZONE_ID, 'hostname': HOSTNAME}])


def _event(hostname=HOSTNAME, myip='1.2.3.4', source_ip='5.6.7.8',
           allowed_hosts=ALLOWED_HOSTS, extra_params=None):
    params = {'hostname': hostname, 'myip': myip}
    if extra_params:
        params.update(extra_params)
    return {
        'headers': {},
        'queryStringParameters': params,
        'requestContext': {
            'identity': {'sourceIp': source_ip},
            'authorizer': {'allowed_hosts': allowed_hosts, 'username': 'testuser'},
        },
    }


@pytest.fixture
def r53_zone():
    with mock_aws():
        r53 = boto3.client('route53', region_name='us-east-1')
        r53.create_hosted_zone(
            Name='example.com.',
            CallerReference='unique-ref-1',
        )
        # Swap to the moto-assigned zone ID — moto returns a fixed ID format
        zones = r53.list_hosted_zones()['HostedZones']
        zone_id = zones[0]['Id'].split('/')[-1]

        # Update allowed hosts to use moto's zone ID
        allowed = json.dumps([{'zone_id': zone_id, 'hostname': HOSTNAME}])
        yield r53, zone_id, allowed


def test_good_new_record(r53_zone):
    r53, zone_id, allowed = r53_zone
    resp = handler(_event(allowed_hosts=allowed), None)
    assert resp['statusCode'] == 200
    assert resp['body'] == f'good 1.2.3.4'


def test_nochg_same_ip(r53_zone):
    r53, zone_id, allowed = r53_zone
    # First update
    handler(_event(allowed_hosts=allowed), None)
    # Second update with same IP
    resp = handler(_event(allowed_hosts=allowed), None)
    assert resp['body'] == 'nochg 1.2.3.4'


def test_good_changed_ip(r53_zone):
    r53, zone_id, allowed = r53_zone
    handler(_event(myip='1.2.3.4', allowed_hosts=allowed), None)
    resp = handler(_event(myip='9.8.7.6', allowed_hosts=allowed), None)
    assert resp['body'] == 'good 9.8.7.6'


def test_notfqdn_missing_hostname(r53_zone):
    r53, zone_id, allowed = r53_zone
    event = _event(allowed_hosts=allowed)
    event['queryStringParameters'].pop('hostname')
    resp = handler(event, None)
    assert resp['body'] == 'notfqdn'


def test_notfqdn_bare_hostname(r53_zone):
    r53, zone_id, allowed = r53_zone
    resp = handler(_event(hostname='barehost', allowed_hosts=allowed), None)
    assert resp['body'] == 'notfqdn'


def test_numhost_too_many(r53_zone):
    r53, zone_id, allowed = r53_zone
    many = ','.join([f'host{i}.example.com' for i in range(21)])
    resp = handler(_event(hostname=many, allowed_hosts=allowed), None)
    assert resp['body'] == 'numhost'


def test_nohost_not_in_allowed_list(r53_zone):
    r53, zone_id, allowed = r53_zone
    resp = handler(_event(hostname='notallowed.example.com', allowed_hosts=allowed), None)
    assert resp['body'] == 'nohost'


def test_myip_defaults_to_source_ip(r53_zone):
    r53, zone_id, allowed = r53_zone
    event = _event(source_ip='7.7.7.7', allowed_hosts=allowed)
    event['queryStringParameters'].pop('myip')
    resp = handler(event, None)
    assert resp['body'] == 'good 7.7.7.7'


def test_multiple_hostnames(r53_zone):
    r53, zone_id, allowed_single = r53_zone
    host2 = 'ddns-test.example.com'
    allowed = json.dumps([
        {'zone_id': zone_id, 'hostname': HOSTNAME},
        {'zone_id': zone_id, 'hostname': host2},
    ])
    resp = handler(_event(hostname=f'{HOSTNAME},{host2}', allowed_hosts=allowed), None)
    lines = resp['body'].splitlines()
    assert len(lines) == 2
    assert lines[0] == 'good 1.2.3.4'
    assert lines[1] == 'good 1.2.3.4'


def test_multiple_hostnames_mixed_results(r53_zone):
    r53, zone_id, allowed_single = r53_zone
    host2 = 'ddns-test.example.com'
    allowed = json.dumps([
        {'zone_id': zone_id, 'hostname': HOSTNAME},
        {'zone_id': zone_id, 'hostname': host2},
    ])
    # Pre-update host1
    handler(_event(hostname=HOSTNAME, myip='1.2.3.4', allowed_hosts=allowed), None)
    # Update both — host1 should be nochg, host2 should be good
    resp = handler(_event(hostname=f'{HOSTNAME},{host2}', myip='1.2.3.4', allowed_hosts=allowed), None)
    lines = resp['body'].splitlines()
    assert lines[0] == 'nochg 1.2.3.4'
    assert lines[1] == 'good 1.2.3.4'


def test_plain_text_content_type(r53_zone):
    r53, zone_id, allowed = r53_zone
    resp = handler(_event(allowed_hosts=allowed), None)
    assert resp['headers']['Content-Type'] == 'text/plain'


def test_all_responses_http_200(r53_zone):
    r53, zone_id, allowed = r53_zone
    for test_event in [
        _event(hostname='bare', allowed_hosts=allowed),
        _event(hostname='notallowed.example.com', allowed_hosts=allowed),
    ]:
        resp = handler(test_event, None)
        assert resp['statusCode'] == 200
