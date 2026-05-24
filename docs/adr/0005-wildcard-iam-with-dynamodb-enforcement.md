# ADR 0005: Wildcard Route53 IAM with DynamoDB-level zone enforcement

**Date:** 2026-05-12  
**Status:** Accepted

## Context

The legacy IAM policy explicitly named a specific hosted zone ARN. Adding a new zone required updating the IAM policy.

Options for the new implementation:
1. List all zone ARNs as CloudFormation parameters, construct explicit IAM policy
2. Allow `arn:aws:route53:::hostedzone/*` at the IAM level; enforce zone scoping in DynamoDB

## Decision

Use a wildcard IAM policy (`arn:aws:route53:::hostedzone/*`) for the update handler's Route53 permissions. Zone and hostname scoping is enforced at the application level via the `allowed_hosts` list in DynamoDB.

## Rationale

- Adding a new zone requires only a DynamoDB entry update, not a CloudFormation stack update
- The DynamoDB `allowed_hosts` mapping is the authoritative source of what each user can update — this is where authorization logic belongs
- The Lambda function constructs the `zone_id` from the DynamoDB mapping (not from client input), so clients cannot inject arbitrary zone IDs
- The IAM wildcard does not grant broader effective access than the explicit list, because the Lambda only operates on zone IDs present in the DynamoDB mapping

## Consequences

- The update handler IAM role has broader IAM permissions than strictly minimum, but is constrained by DynamoDB authorization logic at runtime
- A bug in the DynamoDB authorization logic could allow cross-zone updates within the account; mitigated by unit tests covering the nohost case
- No CloudFormation stack update required to add zones to the service
