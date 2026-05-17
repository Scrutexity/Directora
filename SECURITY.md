# Security Policy

Directora is healthcare-adjacent governance infrastructure. Please report security concerns privately.

## Reporting a Vulnerability

Do not open a public GitHub issue for security concerns.

Report privately through the repository owner or the contact channel listed in the GitHub organization profile.

Please include:

- Description of the issue
- Steps to reproduce
- Affected files, endpoints, or workflows
- Potential impact
- Suggested fix, if known

## Security Principles

Directora is designed around:

- PHI-minimizing references
- Immutable audit trails
- Idempotent request handling
- Signature verification
- Contract drift detection
- Fail-closed behavior
- Least-privilege credentials

## Do Not Submit

Never include:

- Real patient data
- Clinical records
- Secrets, tokens, or credentials
- Private keys
- Production logs containing sensitive data
- Exploit code beyond what is necessary to demonstrate the issue safely

## Compliance Note

This repository does not claim HIPAA, SOC 2, FDA, legal, or regulatory certification. It provides governance mechanisms, auditability patterns, and safer workflow infrastructure.
