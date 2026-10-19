# Compliance profiles: ISO/IEC 27001 first

Roadmap: Q3 in [ROADMAP.md](../ROADMAP.md). Target: v0.6. Item ids: `CMP-n`.

Teams working under ISO/IEC 27001 often have to show, for the controls in their Statement of Applicability, that changes are developed securely and go through change management. A profile they switch on in `.bylaw.toml` makes bylaw review with those controls in mind, tag findings with the Annex A control they touch, and leave an audit trail per pull request.

```toml
profiles = ["iso27001"]
```

**Done when** a repository with the profile on gets findings tagged with Annex A controls (for example secure coding, use of cryptography, logging, data masking, change management), a summary section listing the controls the change touched, and an evidence file per pull request that an auditor can read.

## Items

- [x] **CMP-1** (M) ADR: what a profile is, what bylaw claims and does not claim (it helps with evidence, it does not make anyone compliant), and how the standard's text is handled. Done when: ADR accepted.
- [x] **CMP-2** (M) Profile file format: control ids with bylaw's own short guidance for reviewers, never the standard's text, which is copyrighted. Done when: `profiles/iso27001.toml` with the development-related Annex A 2022 controls, for example 5.34, 8.3 to 8.5, 8.8, 8.9, 8.11, 8.12, 8.15, 8.24, 8.25 to 8.29 and 8.31 to 8.33.
- [x] **CMP-3** (S) `profiles` setting read from the base branch, so a pull request cannot switch a profile off for itself. Done when: config tests.
- [x] **CMP-4** (M) The brief adds the profile's guidance; findings may carry `controls: ["8.28"]`, and validation drops ids the profile does not define. Done when: prompt and validate tests.
- [x] **CMP-5** (M) Severity rules per profile, for example personal data in logs is at least `high` under bylaw's 27001 profile. Done when: tests.
- [ ] **CMP-6** (M) Summary section "Controls touched" and change-management evidence: linked requirement, review done, tests changed, findings resolved or accepted and by whom. Done when: render tests.
- [ ] **CMP-7** (M) Evidence file per pull request (JSON, published as an Actions artifact) for audits. Done when: schema documented, artifact on the demo repository.
- [ ] **CMP-8** (M) Evaluation cases for the profile: changes that break a control and clean ones. Done when: cases in the set, scored.
- [ ] **CMP-9** (S) Docs: what the profile covers, what it does not, and how an auditor reads the evidence. Done when: docs page reviewed by someone who has run a 27001 audit.

## Notes

- Later profiles in the same format: SOC 2, PCI DSS (requirement 6), OWASP ASVS, and data-protection rules such as GDPR and KVKK.
- A profile only adds guidance and tags; every finding still has to pass the same validation as any other.
