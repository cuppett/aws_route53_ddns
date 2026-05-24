# DDNS Route53 — Developer Notes

## Project

DynDNS2-compatible DDNS service built on AWS Lambda (containers), API Gateway, DynamoDB, and Route53.

## Testing Safety

**Always test against a non-production hosted zone.** Any zones with live DDNS records used for real IP connectivity should never be touched during development or integration testing — disrupting them causes actual downtime.

## Running Tests

```bash
python3 -m pip install -r tests/requirements.txt
pytest tests/ -v
```

Tests use `moto` to mock AWS services. No real AWS calls during unit tests.

## Building the Container

```bash
podman build -t ddns-route53:latest -f Containerfile .
```

## Key Files

| File | Purpose |
|------|---------|
| `src/validators.py` | FQDN, IPv4, User-Agent validation |
| `src/dns_utils.py` | Route53 get/upsert helpers |
| `src/authorizer.py` | REQUEST authorizer (Basic Auth + DynamoDB + bcrypt) |
| `src/update_handler.py` | `/nic/update` Lambda (full DynDNS2 protocol) |
| `src/checkip_handler.py` | `/checkip` Lambda |
| `scripts/manage_users.py` | CLI for managing DynamoDB user records (`--password` prompts if omitted; `remove-host` requires `--zone-id`) |
| `cloudformation/ddns_service.yaml` | Main service stack (ECR repo managed separately via aws-codebuild-podman) |

## DynDNS2 Response Codes

`good {IP}`, `nochg {IP}`, `badauth`, `notfqdn`, `nohost`, `numhost`, `badagent`, `dnserr`, `911`

All responses are HTTP 200 with Content-Type: text/plain. Errors are in the body.
