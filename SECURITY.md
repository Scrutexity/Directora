# Security Policy

Directora is healthcare-adjacent governance infrastructure. Treat all security issues as serious, especially anything involving signing, idempotency, ledger integrity, contract drift, or accidental exposure of sensitive data.

## Supported Versions

Security review is focused on the current `main` branch and the latest published release.

| Version | Supported |
|---|---|
| Latest release | Yes |
| `main` | Yes |
| Older releases | Best effort |

## What to Report

Please report issues involving:

- Signature bypass or signature validation weakness
- Idempotency replay conflicts or duplicate commit risk
- Ledger mutation, deletion, or tampering risk
- Contract drift between client and server
- Exposure of secrets, tokens, credentials, or internal keys
- PHI or sensitive clinical data committed to fixtures, logs, or examples
- Authorization, authentication, or least-privilege failures
- CI/CD workflow issues that could bypass governance proof

## Healthcare-Adjacent Handling Rules

Directora should use PHI-minimizing references such as `patient_ref` and `encounter_ref`. Do not include raw patient data, raw clinical content, production identifiers, or screenshots containing sensitive information in public issues.

## Reporting Process

If you believe you found a vulnerability:

1. Do **not** open a public issue with exploit details.
2. Send a private report to the repository owner or maintainer.
3. Include:
   - A clear description of the issue
   - Affected files or endpoints
   - Reproduction steps, if safe
   - Expected vs actual behavior
   - Suggested remediation, if known

## Disclosure Expectations

Please give the maintainer reasonable time to investigate and remediate before public disclosure.

## Scope

This repository demonstrates governance mechanisms and auditability patterns. It is not a HIPAA, SOC 2, HITRUST, FDA, or legal compliance certification.
