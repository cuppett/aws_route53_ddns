import logging

import boto3

logger = logging.getLogger(__name__)


def get_current_record(zone_id: str, hostname: str) -> str | None:
    """Return the current A record value for hostname, or None if not found."""
    r53 = boto3.client('route53')
    normalized = hostname.rstrip('.') + '.'
    resp = r53.list_resource_record_sets(
        HostedZoneId=zone_id,
        StartRecordName=normalized,
        StartRecordType='A',
        MaxItems='1',
    )
    for rrset in resp.get('ResourceRecordSets', []):
        if rrset['Name'].rstrip('.') == hostname.rstrip('.') and rrset['Type'] == 'A':
            records = rrset.get('ResourceRecords', [])
            if records:
                current = records[0]['Value']
                logger.info('Route53 lookup: hostname=%s zone=%s current=%s', hostname, zone_id, current)
                return current
    logger.info('Route53 lookup: hostname=%s zone=%s current=None', hostname, zone_id)
    return None


def upsert_record(zone_id: str, hostname: str, ip: str, ttl: int = 60) -> bool:
    """Create or update an A record. Returns True on success, False on error."""
    r53 = boto3.client('route53')
    try:
        r53.change_resource_record_sets(
            HostedZoneId=zone_id,
            ChangeBatch={
                'Changes': [{
                    'Action': 'UPSERT',
                    'ResourceRecordSet': {
                        'Name': hostname,
                        'Type': 'A',
                        'TTL': ttl,
                        'ResourceRecords': [{'Value': ip}],
                    },
                }],
            },
        )
        logger.info('Route53 UPSERT: hostname=%s ip=%s zone=%s ttl=%d', hostname, ip, zone_id, ttl)
        return True
    except Exception:
        logger.exception('Route53 UPSERT failed for %s in zone %s', hostname, zone_id)
        return False
