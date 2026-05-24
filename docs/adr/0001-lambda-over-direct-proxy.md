# ADR 0001: Lambda in request path instead of direct API Gateway→Route53 proxy

**Date:** 2026-05-12  
**Status:** Accepted

## Context

The legacy implementation uses an API Gateway AWS service proxy integration that calls `Route53:ChangeResourceRecordSets` directly, returning a hardcoded `"good"` response. This is simple and has no cold-start cost, but it cannot:

- Validate input (hostname, IP format)
- Check the current DNS record to return `nochg` when the IP hasn't changed
- Produce any of the DynDNS2 error response codes (`badauth`, `notfqdn`, `nohost`, etc.)
- Enforce per-user hostname authorization beyond the IAM level

The pre-existing implementation used a direct API Gateway service-proxy integration with URI `arn:aws:apigateway:<region>:route53:path/2013-04-01/hostedzone/{hosted_zone_id}/rrset/`.

## Decision

Replace the direct proxy with a Lambda function (`update_handler`) in the request path using `AWS_PROXY` integration. The Lambda handles all validation, Route53 queries (`ListResourceRecordSets` for `nochg` detection), and response formatting.

## Consequences

- Lambda adds ~1–3ms latency in the warm case; cold starts are amortized by the 300s authorizer cache and the fact that DDNS updates are infrequent (typically every 5–15 minutes per client)
- All DynDNS2 response codes are implementable
- Per-user hostname authorization (from DynamoDB) is enforceable in the handler
- Two Route53 API calls per update (ListResourceRecordSets + ChangeResourceRecordSets) instead of one, but this is acceptable given update frequency
