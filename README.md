# DDNS Route53

DynDNS2-compatible Dynamic DNS service built on AWS Lambda, API Gateway, DynamoDB, and Route53.

Replaces the legacy direct API Gateway→Route53 proxy (`xo1u3hdvy7`) with a fully protocol-compliant implementation supporting all standard DynDNS2 response codes, per-user hostname authorization, and `nochg` detection.

## Architecture

```
Client (ddclient / router / inadyn)
  │  GET /nic/update?hostname=X&myip=Y
  │  Authorization: Basic base64(user:pass)
  ▼
API Gateway (REST, REGIONAL)
  ├─ GET /nic/update ──► Authorizer Lambda ──► Update Handler Lambda ──► Route53
  │                       (DynamoDB lookup,      (validate, nochg check,
  │                        bcrypt verify)          upsert A record)
  └─ GET /checkip  ──────► CheckIP Lambda (returns caller's public IP)
```

Authentication is HTTP Basic Auth. Credentials are stored per-user in DynamoDB with bcrypt-hashed passwords and a list of allowed hostnames per user.

## Response Codes

All responses are HTTP 200 with `Content-Type: text/plain`.

| Code | Meaning |
|------|---------|
| `good {IP}` | Record updated successfully |
| `nochg {IP}` | IP already matched — no update needed |
| `badauth` | Authentication failed |
| `notfqdn` | Hostname is not a valid FQDN |
| `nohost` | Hostname not in your allowed list |
| `numhost` | More than 20 hostnames in one request |
| `badagent` | Missing or disallowed User-Agent |
| `dnserr` | Route53 error — retry after 30 minutes |
| `911` | Internal error — retry after 30 minutes |

## Deployment

### Prerequisites

- AWS CLI with `cuppett` profile configured
- Podman installed
- Python 3.x and `bcrypt`, `boto3` installed locally for user management

### 1. Create the ECR repository

Use the [aws-codebuild-podman](https://github.com/cuppett/aws-codebuild-podman) or [aws-ecr-mirror](https://github.com/cuppett/aws-ecr-mirror) CloudFormation templates to create an ECR repository named `ddns-route53`.

### 2. Build and push the container image

```bash
make push
```

### 3. Deploy the service stack

```bash
make deploy-service
```

To override parameters:

```bash
aws cloudformation deploy \
  --template-file cloudformation/ddns_service.yaml \
  --stack-name ddns-route53 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ImageUri=771294529343.dkr.ecr.us-east-1.amazonaws.com/ddns-route53:latest \
    RecordTtl=60 \
    StageName=v1 \
  --profile cuppett
```

With optional custom domain:

```bash
aws cloudformation deploy \
  --template-file cloudformation/ddns_service.yaml \
  --stack-name ddns-route53 \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    ImageUri=771294529343.dkr.ecr.us-east-1.amazonaws.com/ddns-route53:latest \
    CustomDomainName=ddns.cuppett.dev \
    CertificateArn=arn:aws:acm:us-east-1:771294529343:certificate/... \
    HostedZoneIdForDomain=Z07412393IK1HEEHEGRPG \
  --profile cuppett
```

### 4. Add users

```bash
# Add user allowed to update test.cuppett.dev (use cuppett.dev for testing)
python scripts/manage_users.py add-user \
  --username mydevice \
  --password 'a-strong-password' \
  --hosts 'Z07412393IK1HEEHEGRPG:test.cuppett.dev' \
  --profile cuppett

# Add production user (after validation)
python scripts/manage_users.py add-user \
  --username google-isp \
  --password 'a-strong-password' \
  --hosts 'ZYD1DIOLOG0D0:google.cuppett.com' \
  --profile cuppett
```

## Client Configuration

### curl (testing)

```bash
API=https://APIGW_ID.execute-api.us-east-1.amazonaws.com/v1

# Update a record
curl -u mydevice:password "$API/nic/update?hostname=test.cuppett.dev&myip=1.2.3.4" \
  -H "User-Agent: TestClient/1.0 you@example.com"

# Check your public IP
curl "$API/checkip"
```

### ddclient

```ini
# /etc/ddclient.conf
protocol=dyndns2
server=APIGW_ID.execute-api.us-east-1.amazonaws.com/v1
ssl=yes
login=mydevice
password=a-strong-password
use=web, web=APIGW_ID.execute-api.us-east-1.amazonaws.com/v1/checkip
test.cuppett.dev
```

With a custom domain (`ddns.cuppett.dev`):

```ini
protocol=dyndns2
server=ddns.cuppett.dev
ssl=yes
login=mydevice
password=a-strong-password
use=web, web=https://ddns.cuppett.dev/checkip, web-skip='Current IP Address: '
test.cuppett.dev
```

### ASUS Merlin (custom DDNS script)

Place in `/jffs/scripts/ddns-start`:

```bash
#!/bin/sh
IP="$1"
RESULT=$(curl -s -u mydevice:password \
  "https://ddns.cuppett.dev/nic/update?hostname=myhome.cuppett.dev&myip=$IP" \
  -H "User-Agent: ASUS-Merlin/386 ddns-start")
/sbin/ddns_custom_updated $(echo "$RESULT" | grep -q "^good\|^nochg" && echo 1 || echo 0)
```

## User Management

All subcommands accept `--profile`, `--region`, and `--table` (default `DDNSAuthorization`).
`--password` may be omitted from `add-user` and `update-password` to be prompted interactively.

```bash
python scripts/manage_users.py --help

# List all users
python scripts/manage_users.py list-users --profile cuppett

# Add a hostname to an existing user
python scripts/manage_users.py add-host \
  --username mydevice \
  --zone-id Z07412393IK1HEEHEGRPG \
  --hostname home.cuppett.dev \
  --profile cuppett

# Remove a hostname from a user
python scripts/manage_users.py remove-host \
  --username mydevice \
  --zone-id Z07412393IK1HEEHEGRPG \
  --hostname home.cuppett.dev \
  --profile cuppett

# Disable a user (immediate effect after authorizer cache TTL)
python scripts/manage_users.py disable-user --username mydevice --profile cuppett

# Re-enable a disabled user
python scripts/manage_users.py enable-user --username mydevice --profile cuppett

# Change password (prompts if --password is omitted)
python scripts/manage_users.py update-password \
  --username mydevice --password 'new-password' --profile cuppett

# Permanently delete a user
python scripts/manage_users.py remove-user --username mydevice --profile cuppett
```

## Development

```bash
# Install test dependencies
make install

# Run tests
make test

# Build container locally
make build
```

Tests use `moto` to mock AWS services — no real AWS calls during unit tests.

## Migration from Legacy Implementation

The legacy API Gateway (`xo1u3hdvy7`) uses a direct AWS service proxy with a single shared token in SSM (`DDNS_ROUTE53_AUTHORIZATION`). Migration steps:

1. Deploy this stack alongside the legacy one (different API Gateway ID)
2. Test all response codes against the new endpoint using `cuppett.dev` hostnames
3. Recreate users in DynamoDB matching the current device configuration
4. Update client configuration to point to the new API Gateway URL
5. Once all clients are migrated, delete the legacy API Gateway, Lambda (`AuthorizeDDNS`), IAM roles (`API_GW_Route53`, `Read_SSM_Route53_Parameter`), and SSM parameter

## Design Decisions

See [`docs/adr/`](docs/adr/) for Architecture Decision Records covering:

- [ADR 0001](docs/adr/0001-lambda-over-direct-proxy.md) — Lambda in request path vs direct proxy
- [ADR 0002](docs/adr/0002-dynamodb-auth-mapping.md) — DynamoDB for auth and hostname mapping
- [ADR 0003](docs/adr/0003-single-container-multi-handler.md) — Single container image with multiple entry points
- [ADR 0004](docs/adr/0004-request-authorizer-type.md) — REQUEST-type authorizer
- [ADR 0005](docs/adr/0005-wildcard-iam-with-dynamodb-enforcement.md) — Wildcard IAM with DynamoDB enforcement
