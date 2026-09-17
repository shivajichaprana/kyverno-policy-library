# Supply-chain policies

Three policies asking three different questions about the same image, in the order they
stop being answerable by the previous one.

| Policy | Rules | What it catches |
|---|---|---|
| `require-build-provenance.yaml` | `verify-slsa-provenance` | An image with no verifiable account of how it was built, and provenance that is correctly signed but says the wrong thing |
| `require-sbom-attestation.yaml` | `verify-sbom-is-present-and-readable`, `reject-known-bad-dependency-versions` | An SBOM that is absent, empty, or in a format the rest of the checks cannot read — and, once it is readable, a dependency version this organisation has banned |
| `require-recent-vulnerability-scan.yaml` | `verify-scan-and-database-are-recent` | A scan result that is perfectly signed and out of date, and a recent scan run against a stale vulnerability database |

## Before applying these

| Replace | In | With |
|---|---|---|
| `registry.example.com/*` | all three | The registry pattern matching images your organisation builds |
| `https://github.com/<your-org>/*/.github/workflows/*` | all three | The workflow identity permitted to sign attestations |
| `https://github.com/<your-org>/<your-repo>/.github/workflows/release.yaml@refs/heads/main` | `require-build-provenance.yaml` | The builder identity your provenance actually declares |
| `log4j-core` and its version list | `require-sbom-attestation.yaml` | The dependencies your organisation has decided must never run again |

`https://token.actions.githubusercontent.com` and `https://rekor.sigstore.dev` are the
public GitHub OIDC issuer and the public transparency log, and are left as they are.

```sh
kubectl apply -f policies/supply-chain/
kubectl get policyreport -A
```

## What a signature actually proves

It proves who published a statement. That is all, and every failure in this set comes from
quietly treating it as more.

| The statement | The signature proves | The signature does not prove |
|---|---|---|
| Provenance | This identity published a provenance document for this image | That the document describes how the image was really built |
| SBOM | This identity published a component list | That the list is complete, or even non-empty |
| Vulnerability scan | This identity ran a scan and recorded the result | That the result is still true today |

The right-hand column is what the `conditions` block in each policy is for.

## The check that verifies nothing

`conditions` is optional. An attestation rule written without it verifies that a signed
document of the declared predicate type exists, and nothing at all about its contents:

```yaml
attestations:
  - predicateType: https://slsa.dev/provenance/v1
    attestors:
      - entries:
          - keyless:
              subject: https://github.com/<your-org>/*
              issuer: https://token.actions.githubusercontent.com
```

A provenance statement asserting that the image was built by hand, from uncommitted
source, on somebody's laptop, passes that completely — as long as it carries the right
signature. From outside, a rule with no conditions and a rule doing real work produce the
same report entry. The schema requires an attestor and does not require a condition, so
the half that can be forgotten is the half that reads the document.

## Predicate types are exact strings

`predicateType` selects which attestation is read, by exact match. There is no fuzzy
resolution and no warning for a type nothing publishes. Two of the three types in this set
have more than one spelling in circulation:

| Type | Written as |
|---|---|
| Cosign vulnerability scan | `https://cosign.sigstore.dev/attestation/vuln/v1` in cosign's own specification, `cosign.sigstore.dev/attestation/vuln/v1` in Kyverno's sample library |
| CycloneDX SBOM | `https://cyclonedx.org/schema` in Kyverno's sample library; other tooling has used `https://cyclonedx.org/bom` |

Read it off a real attestation rather than trusting a document:

```sh
cosign download attestation <image> | jq -r '.payload | @base64d | fromjson | .predicateType'
```

The condition paths depend on the same decision. SLSA v0.2 and SLSA v1 are different
shapes, not a version bump — `builder.id` against `runDetails.builder.id`, `buildType`
against `buildDefinition.buildType`. Changing the predicate type without changing the
paths gives a rule whose every condition reads nothing.

## Why "must not contain" is the weakest shape

A filter over a component list returns an empty list when nothing matches, and an empty
list satisfies `AllNotIn`. Three different situations produce that same pass:

- the image genuinely does not contain the package
- the SBOM lists nothing at all
- the SBOM is SPDX, which calls them `packages`, so `components` resolves to nothing

Only the first is good news. `verify-sbom-is-present-and-readable` is what separates them,
and it runs as its own rule so that a report entry says which of the three happened.

## Freshness is a second clock, and then a third

`metadata.scanFinishedOn` says when the scan ran. `scanner.db.lastUpdate` says how current
the vulnerability database was when it ran. A scan from an hour ago against a database
from six months ago is fresh by the measure everyone checks and blind to six months of
disclosures — and reports zero findings, which is what a clean image reports.

Both windows are measured from now, so they are not independent:

| Window | Value | Why |
|---|---|---|
| Scan age | `168h` | A week |
| Database age | `192h` | The scan window plus a day of permitted database lag at scan time |

If the database window is not larger than the scan window, the two conditions can never
both hold and every image fails forever. Tighten one and the other has to move with it.

## What this set does not do

- **It does not read scan findings.** Whether an image with a known vulnerability may run
  is a severity-and-exception decision, and the pipeline gate is where a fix version and a
  waiver can be recorded together. A policy that relitigates it here ends up holding a list
  of exemptions it cannot explain.
- **It does not keep a CVE list current.** The banned-dependency rule is for the handful of
  things an organisation has decided must never run again. A list that needs editing faster
  than a policy repository can review changes is a list that is behind, and a list that is
  behind reports clean.
- **It does not see anything installed at runtime.** An SBOM describes the image as built.
- **It does not notice revocation for up to an hour.** Kyverno caches a successful
  verification, `imageVerifyCacheTTLDuration` on the admission controller sets for how long,
  and during that window a revoked attestation is still accepted with nothing reporting
  otherwise.
- **It does not cover images outside the matched registry.** Verify what you sign; demanding
  attestations from every vendor image leaves nothing schedulable on a restarted node.
