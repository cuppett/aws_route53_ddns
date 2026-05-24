#!/usr/bin/env python3
"""CLI tool for managing DDNS Route53 authorization records in DynamoDB."""

import argparse
import datetime
import getpass
import sys

import bcrypt
import boto3
from botocore.exceptions import ClientError


DEFAULT_TABLE = 'DDNSAuthorization'


def _table(args):
    session = boto3.Session(profile_name=getattr(args, 'profile', None))
    ddb = session.resource('dynamodb', region_name=getattr(args, 'region', 'us-east-1'))
    return ddb.Table(args.table)


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')


def _hash_password(password: str) -> str:
    if not password:
        print('ERROR: Password must not be empty.', file=sys.stderr)
        sys.exit(1)
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def _read_password(provided: str | None) -> str:
    if provided is not None:
        return provided
    pw = getpass.getpass('Password: ')
    if getpass.getpass('Confirm: ') != pw:
        print('ERROR: Passwords do not match.', file=sys.stderr)
        sys.exit(1)
    return pw


def _parse_hosts(hosts_str: str) -> list[dict]:
    """Parse 'ZONE_ID:hostname,ZONE_ID:hostname' into list of dicts."""
    result = []
    for entry in hosts_str.split(','):
        entry = entry.strip()
        if not entry:
            continue
        if ':' not in entry:
            print(f"ERROR: Invalid host entry '{entry}' — expected ZONE_ID:hostname", file=sys.stderr)
            sys.exit(1)
        zone_id, hostname = entry.split(':', 1)
        result.append({'zone_id': zone_id.strip(), 'hostname': hostname.strip()})
    return result


def cmd_add_user(args):
    table = _table(args)
    existing = table.get_item(Key={'username': args.username}).get('Item')
    if existing:
        print(f"ERROR: User '{args.username}' already exists. Use update-password or add-host.", file=sys.stderr)
        sys.exit(1)

    allowed_hosts = _parse_hosts(args.hosts) if args.hosts else []
    password = _read_password(args.password)
    now = _now()
    table.put_item(Item={
        'username': args.username,
        'password_hash': _hash_password(password),
        'enabled': True,
        'allowed_hosts': allowed_hosts,
        'created_at': now,
        'updated_at': now,
    })
    print(f"Created user '{args.username}' with {len(allowed_hosts)} host(s).")


def cmd_list_users(args):
    table = _table(args)
    items = []
    kwargs = {'ProjectionExpression': 'username, enabled, allowed_hosts, updated_at'}
    while True:
        resp = table.scan(**kwargs)
        items.extend(resp.get('Items', []))
        if 'LastEvaluatedKey' not in resp:
            break
        kwargs['ExclusiveStartKey'] = resp['LastEvaluatedKey']
    items.sort(key=lambda x: x['username'])
    if not items:
        print('No users found.')
        return
    for item in items:
        status = 'enabled' if item.get('enabled', True) else 'DISABLED'
        hosts = item.get('allowed_hosts', [])
        host_list = ', '.join(f"{h['hostname']} ({h['zone_id']})" for h in hosts) or '(none)'
        print(f"  {item['username']}  [{status}]  hosts: {host_list}  updated: {item.get('updated_at', '?')}")


def cmd_disable_user(args):
    table = _table(args)
    try:
        table.update_item(
            Key={'username': args.username},
            UpdateExpression='SET enabled = :v, updated_at = :t',
            ExpressionAttributeValues={':v': False, ':t': _now()},
            ConditionExpression='attribute_exists(username)',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"ERROR: User '{args.username}' not found.", file=sys.stderr)
            sys.exit(1)
        raise
    print(f"Disabled user '{args.username}'.")


def cmd_enable_user(args):
    table = _table(args)
    try:
        table.update_item(
            Key={'username': args.username},
            UpdateExpression='SET enabled = :v, updated_at = :t',
            ExpressionAttributeValues={':v': True, ':t': _now()},
            ConditionExpression='attribute_exists(username)',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"ERROR: User '{args.username}' not found.", file=sys.stderr)
            sys.exit(1)
        raise
    print(f"Enabled user '{args.username}'.")


def cmd_remove_user(args):
    table = _table(args)
    try:
        table.delete_item(
            Key={'username': args.username},
            ConditionExpression='attribute_exists(username)',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"ERROR: User '{args.username}' not found.", file=sys.stderr)
            sys.exit(1)
        raise
    print(f"Removed user '{args.username}'.")


def cmd_update_password(args):
    table = _table(args)
    password = _read_password(args.password)
    try:
        table.update_item(
            Key={'username': args.username},
            UpdateExpression='SET password_hash = :h, updated_at = :t',
            ExpressionAttributeValues={':h': _hash_password(password), ':t': _now()},
            ConditionExpression='attribute_exists(username)',
        )
    except ClientError as e:
        if e.response['Error']['Code'] == 'ConditionalCheckFailedException':
            print(f"ERROR: User '{args.username}' not found.", file=sys.stderr)
            sys.exit(1)
        raise
    print(f"Updated password for '{args.username}'.")


def cmd_add_host(args):
    table = _table(args)
    item = table.get_item(Key={'username': args.username}).get('Item')
    if not item:
        print(f"ERROR: User '{args.username}' not found.", file=sys.stderr)
        sys.exit(1)

    hosts = list(item.get('allowed_hosts', []))
    for h in hosts:
        if h['hostname'] == args.hostname and h['zone_id'] == args.zone_id:
            print(f"Host '{args.hostname}' (zone {args.zone_id}) already in allowed list for '{args.username}'.")
            return

    hosts.append({'zone_id': args.zone_id, 'hostname': args.hostname})
    table.update_item(
        Key={'username': args.username},
        UpdateExpression='SET allowed_hosts = :h, updated_at = :t',
        ExpressionAttributeValues={':h': hosts, ':t': _now()},
    )
    print(f"Added host '{args.hostname}' (zone {args.zone_id}) for user '{args.username}'.")


def cmd_remove_host(args):
    table = _table(args)
    item = table.get_item(Key={'username': args.username}).get('Item')
    if not item:
        print(f"ERROR: User '{args.username}' not found.", file=sys.stderr)
        sys.exit(1)

    hosts = [
        h for h in item.get('allowed_hosts', [])
        if not (h['hostname'] == args.hostname and h['zone_id'] == args.zone_id)
    ]
    table.update_item(
        Key={'username': args.username},
        UpdateExpression='SET allowed_hosts = :h, updated_at = :t',
        ExpressionAttributeValues={':h': hosts, ':t': _now()},
    )
    print(f"Removed host '{args.hostname}' (zone {args.zone_id}) from user '{args.username}'.")


def main():
    parser = argparse.ArgumentParser(description='Manage DDNS Route53 authorization records')
    parser.add_argument('--table', default=DEFAULT_TABLE, help='DynamoDB table name')
    parser.add_argument('--profile', default=None, help='AWS profile name')
    parser.add_argument('--region', default='us-east-1', help='AWS region')

    sub = parser.add_subparsers(dest='command', required=True)

    p = sub.add_parser('add-user', help='Create a new DDNS user')
    p.add_argument('--username', required=True)
    p.add_argument('--password', default=None, help='Password (prompted if omitted)')
    p.add_argument('--hosts', default='', help='Comma-separated ZONE_ID:hostname pairs')

    sub.add_parser('list-users', help='List all DDNS users')

    p = sub.add_parser('disable-user', help='Disable a user (blocks authentication)')
    p.add_argument('--username', required=True)

    p = sub.add_parser('enable-user', help='Re-enable a disabled user')
    p.add_argument('--username', required=True)

    p = sub.add_parser('remove-user', help='Permanently delete a user')
    p.add_argument('--username', required=True)

    p = sub.add_parser('update-password', help="Change a user's password")
    p.add_argument('--username', required=True)
    p.add_argument('--password', default=None, help='New password (prompted if omitted)')

    p = sub.add_parser('add-host', help="Add a hostname to a user's allowed list")
    p.add_argument('--username', required=True)
    p.add_argument('--zone-id', required=True, dest='zone_id')
    p.add_argument('--hostname', required=True)

    p = sub.add_parser('remove-host', help="Remove a hostname from a user's allowed list")
    p.add_argument('--username', required=True)
    p.add_argument('--zone-id', required=True, dest='zone_id')
    p.add_argument('--hostname', required=True)

    args = parser.parse_args()
    commands = {
        'add-user': cmd_add_user,
        'list-users': cmd_list_users,
        'disable-user': cmd_disable_user,
        'enable-user': cmd_enable_user,
        'remove-user': cmd_remove_user,
        'update-password': cmd_update_password,
        'add-host': cmd_add_host,
        'remove-host': cmd_remove_host,
    }
    commands[args.command](args)


if __name__ == '__main__':
    main()
