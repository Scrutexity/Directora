# Contributing to Directora

Directora is governance infrastructure. Contributions should preserve the core guarantees: atomicity, idempotency, contract integrity, and auditability.

## Contribution Rules

1. **Do not weaken governance checks.**  
   Any change that touches signing, ledger writes, idempotency, contract validation, or replay behavior must include tests.

2. **Keep the shared contract canonical.**  
   `shared/brief-api-contract.json` is the golden artifact. Client and server changes must stay aligned with it.

3. **No PHI or sensitive fixtures.**  
   Do not commit patient data, raw clinical content, production identifiers, secrets, tokens, or real encounter details.

4. **Fail closed.**  
   Signature mismatch, contract drift, replay conflicts, malformed payloads, and unsafe state transitions should fail explicitly.

5. **Prefer small pull requests.**  
   Governance systems are easier to review when changes are narrow and testable.

## Local Checks

Before opening a pull request:

```bash
python -m pytest
./tests/governance/ultimate-governance-check.sh
```

## Pull Request Checklist

- [ ] Change is scoped and easy to review
- [ ] Governance tests pass
- [ ] Contract changes are intentional and documented
- [ ] No secrets, PHI, or production identifiers are included
- [ ] README/docs updated if behavior changed

## Documentation

If you change a public endpoint, contract field, SDK behavior, or governance invariant, update the relevant documentation in `README.md` or `docs/`.
