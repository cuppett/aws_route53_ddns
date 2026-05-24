import json
import logging
import os

from src.dns_utils import get_current_record, upsert_record
from src.validators import validate_fqdn, validate_ipv4

logging.getLogger().setLevel(os.environ.get('LOG_LEVEL', 'INFO'))
logger = logging.getLogger(__name__)

RECORD_TTL = int(os.environ.get('RECORD_TTL', '60'))
MAX_HOSTNAMES = 20


def _plain(body: str) -> dict:
    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'text/plain'},
        'body': body,
    }


def handler(event, context):
    try:
        return _handle(event)
    except Exception:
        logger.exception('Unhandled error in update handler')
        return _plain('911')


def _handle(event):
    raw_headers = event.get('headers') or {}
    # API Gateway may lowercase header names; do a case-insensitive lookup
    headers = {k.lower(): v for k, v in raw_headers.items()}
    params = event.get('queryStringParameters') or {}
    authorizer = (event.get('requestContext') or {}).get('authorizer') or {}
    source_ip = (event.get('requestContext') or {}).get('identity', {}).get('sourceIp', '')

    # Parse hostname parameter
    hostname_param = params.get('hostname', '').strip()
    if not hostname_param:
        return _plain('notfqdn')

    hostnames = [h.strip() for h in hostname_param.split(',') if h.strip()]
    if not hostnames:
        return _plain('notfqdn')
    if len(hostnames) > MAX_HOSTNAMES:
        return _plain('numhost')

    # Determine IP address
    ip = params.get('myip', '').strip() or source_ip
    if not validate_ipv4(ip):
        return _plain('dnserr')

    username = authorizer.get('username', 'unknown')
    logger.info('Request: user=%s src_ip=%s ip=%s hostnames=%s', username, source_ip, ip, hostnames)

    # Build allowed hosts lookup from authorizer context
    try:
        allowed_hosts_raw = json.loads(authorizer.get('allowed_hosts', '[]'))
        # Map hostname -> zone_id for fast lookup
        allowed_map = {entry['hostname'].rstrip('.'): entry['zone_id'] for entry in allowed_hosts_raw}
    except (json.JSONDecodeError, KeyError):
        logger.error('Invalid allowed_hosts in authorizer context')
        return _plain('911')

    results = []
    for hostname in hostnames:
        result = _process_hostname(hostname, ip, allowed_map)
        logger.info('Result: user=%s hostname=%s ip=%s outcome=%s', username, hostname, ip, result)
        results.append(result)

    return _plain('\n'.join(results))


def _process_hostname(hostname: str, ip: str, allowed_map: dict) -> str:
    if not validate_fqdn(hostname):
        return 'notfqdn'

    zone_id = allowed_map.get(hostname.rstrip('.'))
    if not zone_id:
        return 'nohost'

    current = get_current_record(zone_id, hostname)
    if current == ip:
        return f'nochg {ip}'

    if upsert_record(zone_id, hostname, ip, ttl=RECORD_TTL):
        return f'good {ip}'
    return 'dnserr'
