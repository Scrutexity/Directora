# Contributing to Directora

Directora is governance infrastructure. Contributions should be small, reviewable, and safe.

## Pull Request Rules

Before opening a pull request:

1. Run the governance check.

```bash
./tests/governance/ultimate-governance-check.sh
```

2. Keep contract changes deliberate and versioned.
3. Do not add PHI, secrets, tokens, private keys, or sensitive production logs.
4. Update documentation when behavior changes.
5. Keep client and server behavior aligned.
6. Prefer explicit failure over silent fallback.

## PR Checklist

- [ ] Governance check passes
- [ ] Tests pass
- [ ] No sensitive data added
- [ ] Contract changes are intentional
- [ ] README/docs updated if behavior changed
- [ ] Public integration surface remains stable or versioned

## Engineering Standard

Directora favors:

- Atomic commits
- Idempotent behavior
- Immutable event references
- Fail-closed security posture
- Minimal, readable interfaces
