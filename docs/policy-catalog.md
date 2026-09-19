# Policy catalog

Every rule in the library, in one place, so that a line in a policy report can be looked
up without reading the policy that produced it.

A finding names a policy and a rule:

```
policy require-resource-requests-and-limits/require-memory-limits fail: ...
```

The tables below are keyed on exactly that pair. Each set also has its own README carrying
the reasoning behind its rules; this document is the index, not the argument.

## At a glance

| | |
|---|---|
| Policy sets | 6 |
| `ClusterPolicy` documents | 13 |
| Supporting documents | 1 (`ClusterRole`) |
| Rules | 23 — 16 validating, 5 image-verification, 2 generating |
| Rules shipping in Enforce | 0 |
| Policies carrying a value you must substitute | 8 |
| Namespaces every rule excludes | `kube-system`, `kube-node-lease`, `kube-public`, `kyverno` |

Severity in the tables is the policy's own `policies.kyverno.io/severity` annotation, which
is what a report tool sorts on. It describes the consequence of the thing the rule
catches, not how likely it is.

## Reading a finding

A failing rule means one of three things, and telling them apart is the first job:

1. **A real violation.** The workload does the thing the rule describes. The message on
   the rule says what to change.
2. **A placeholder that has not been substituted.** Eight policies carry a registry, an
   organisation, a key or a label key that stands in for one of yours. Until those are
   edited, their findings describe this library's example values rather than your cluster.
   The [substitution table](#substitution-the-rules-that-are-inert-until-edited) lists
   every one.
3. **A false positive in the library.** Rarer, and worth reporting. The pipeline applies
   every validating policy to a single workload that satisfies all of them at once, so a
   rule that cannot be satisfied alongside its neighbours is caught before release — but
   only for the shapes that one workload happens to have.

A rule that reports **nothing** is the case this library is written around, and it is not
on that list because it never appears in a report at all. See
[Coverage](#coverage-what-is-verified-and-what-is-not).

## `policies/images/` — what may run

| Policy | Rule | Applies to | Rejects | Severity |
|---|---|---|---|---|
| `restrict-image-registries` | `validate-registries` | Pod | An image whose **normalised** registry is not approved. An image with no registry prefix normalises to Docker Hub, so `nginx` is rejected for the same reason `docker.io/library/nginx` is. | high |
| `restrict-image-registries` | `restrict-repository-paths` | Pod | An image from a shared public registry that sits outside the approved repository path. A hostname identifies a registry, not a publisher. | high |
| `disallow-mutable-image-tags` | `require-image-tag` | Pod | An image with no tag and no digest. It is pulled as `:latest`, so what runs is decided at pull time rather than at deploy time. | medium |
| `disallow-mutable-image-tags` | `disallow-latest-tag` | Pod | An image tagged `latest`. | medium |
| `require-image-signatures` | `verify-internal-images` | Pod | An image from the internal registry with no valid Cosign signature. Reaching a verdict needs a registry round trip, so this policy does not run in background scans. | high |

## `policies/pod-security/` — how a Pod must be configured

| Policy | Rule | Applies to | Rejects | Severity |
|---|---|---|---|---|
| `require-pod-security-standards` | `validate-baseline-profile` | Pod | A Pod outside the Pod Security Standards **baseline** profile — privilege escalation, host namespaces, host ports, unsafe volume types and the rest of that set. | high |
| `require-pod-security-standards` | `validate-restricted-profile` | Pod | A Pod outside the **restricted** profile, which is inclusive of baseline and additionally requires non-root execution, a seccomp profile and a dropped capability set. | high |
| `require-read-only-root-filesystem` | `validate-read-only-root-filesystem` | Pod | A container that does not set `readOnlyRootFilesystem: true`. This control is in **neither** profile above — it was a PodSecurityPolicy field that the standards did not carry forward. | medium |

Both profile rules are a `podSecurity` subrule rather than a hand-written pattern, because
the fields involved may be set at the Pod level, the container level or both, and only the
library Pod Security Admission itself uses resolves that correctly. They are two
independent rules so that the usual adoption path — baseline to Enforce first, restricted
left in Audit — is one field edit. A Pod violating baseline is therefore reported twice,
once by each rule, until baseline is clean.

## `policies/resources/` — what a workload may consume

| Policy | Rule | Applies to | Rejects | Severity |
|---|---|---|---|---|
| `require-resource-requests-and-limits` | `require-resource-requests` | Pod | A container with no CPU and memory requests. Without them the Pod is BestEffort: scheduled as though it needs nothing, evicted first when the node runs short. | medium |
| `require-resource-requests-and-limits` | `require-memory-limits` | Pod | A container with no memory limit. Memory cannot be reclaimed by slowing a container down, so an unbounded container is bounded only by the node, and its neighbours are what get evicted. | medium |
| `require-safe-disruption-budgets` | `disallow-blocking-budgets` | PodDisruptionBudget | A budget that can never permit a voluntary eviction — `maxUnavailable: 0` or `minAvailable: 100%`. A node drain against one waits indefinitely. | high |
| `require-safe-disruption-budgets` | `require-explicit-budget-selector` | PodDisruptionBudget | A budget with an empty or absent `selector`. An empty selector covers every pod in the namespace on `policy/v1` and covered none on the removed `policy/v1beta1`; the same manifest reversed its meaning across that upgrade. | high |
| `require-topology-spread-constraints` | `require-spread-label-selector` | Pod | A spread constraint with no `labelSelector`. It counts no pods and is satisfied by any placement — the field is present, the workload declares spreading, and no scheduling decision is affected. | medium |
| `require-topology-spread-constraints` | `require-enforced-spread` | Pod | A spread constraint set to `whenUnsatisfiable: ScheduleAnyway`, which the scheduler discards when it cannot be met. This is the rule to argue with; the set README makes the case both ways. | medium |
| `require-topology-spread-constraints` | `require-spread-for-labelled-workloads` | Pod | A workload **labelled** as needing spread that declares no constraints. Opt-in, because a single-replica Pod, a Job and a DaemonSet each have good reasons not to be spread. | medium |

The requests rule covers `containers` and `initContainers` but **not**
`ephemeralContainers`, and that is the library's one documented exception to checking all
three lists: the API forbids `resources` there, so requiring it would describe a Pod that
cannot be submitted.

## `policies/network/` — what identity a workload declares

| Policy | Rule | Applies to | Rejects | Severity |
|---|---|---|---|---|
| `require-network-identity-labels` | `require-identity-labels` | Pod | A Pod missing `app.kubernetes.io/name` or the network tier label. It is selected by no NetworkPolicy, which in a namespace with no default-deny is indistinguishable from being deliberately unrestricted. | medium |
| `require-network-identity-labels` | `require-known-network-tier` | Pod | A tier label whose **value** is outside the approved set. `tier: frontned` is a valid label: the Pod runs, a presence check passes, and nothing written for `frontend` selects it. | medium |

## `policies/supply-chain/` — what the build must prove

All four rules verify a signed attestation on images from the internal registry. Each pins
both halves: `attestors` says who signed, `conditions` reads what was said. A rule with
attestors and no conditions passes provenance asserting the image was built by hand on a
laptop, so an attestation without conditions is treated here as a defect rather than an
option.

| Policy | Rule | Predicate type | Conditions asserted | Severity |
|---|---|---|---|---|
| `require-build-provenance` | `verify-slsa-provenance` | `https://slsa.dev/provenance/v1` | 2 — the builder identity the document claims matches the identity that signed it, and the build type is the hosted-workflow one | high |
| `require-sbom-attestation` | `verify-sbom-is-present-and-readable` | `https://cyclonedx.org/schema` | 2 — the document is CycloneDX, and it lists at least one component | medium |
| `require-sbom-attestation` | `reject-known-bad-dependency-versions` | `https://cyclonedx.org/schema` | 1 — no component matches the banned-version list | medium |
| `require-recent-vulnerability-scan` | `verify-scan-and-database-are-recent` | `https://cosign.sigstore.dev/attestation/vuln/v1` | 2 — the scan is recent **and** the vulnerability database was recent when the scan ran | medium |

The two SBOM rules are separate on purpose. The banned-version rule asks whether a
forbidden component is listed, and a filter over an empty list returns an empty list — so
an SBOM listing nothing, or an SPDX document, which calls them `packages`, passes it
exactly the way a genuinely clean image does. The readability rule is what turns those
three situations into different answers.

Predicate types are exact strings. A type that does not match is not a mismatch error; it
is an attestation the rule does not find, and `required: true` is what turns that into a
finding rather than a silent pass.

## `policies/generate/` — what Kyverno creates

This set has no Audit mode: a generate rule creates its resource or it does not. The same
default is expressed as a match condition instead — both rules match only a Namespace
carrying the opt-in label, so as shipped the set acts on nothing.

| Policy | Rule | Triggered by | Creates |
|---|---|---|---|
| `add-default-network-policies` | `add-deny-all` | Namespace with the opt-in label | `NetworkPolicy/default-deny-all`, both `policyTypes`, synchronised |
| `add-default-network-policies` | `add-dns-egress` | Namespace with the opt-in label | `NetworkPolicy/allow-dns-egress`, UDP and TCP on 53, synchronised |

Both rules live in one file so the deny cannot be applied without the DNS exception that
makes it survivable. Deny-all egress blocks name resolution, and the symptom —
applications failing to reach things by name — reads as an application fault.

`background-controller-rbac.yaml` is not a policy. It is the `ClusterRole`, aggregated to
Kyverno's background controller, granting `create`, `update`, `patch`, `delete`, `get`,
`list` and `watch` on `networkpolicies`. Without it the policy is accepted, reports
`Ready`, and creates nothing — generation does not happen during admission, so there is no
admission failure to see.

## Enforcement state

Every validating and image-verification rule ships with `failureAction: Audit`, set per
rule rather than per policy, so the mode of a rule is readable beside the rule.

| State | Rules |
|---|---|
| `Audit` | 21 |
| `Enforce` | 0 |
| No failure action (generate) | 2 |

Turning one on is a single field edit. One control is coupled to that edit rather than
independent of it: `verifyImages[*].mutateDigest` rewrites a verified tag to its digest,
and Kyverno **refuses** that setting while the failure action is `Audit`, so the rewrite
becomes available at the same moment the rule starts blocking. That is a cross-field check
inside Kyverno's own policy validation — nothing structural can see it, and a policy
setting both is rejected outright by `kubectl apply`.

## Substitution: the rules that are inert until edited

Eight policies carry an example value. Their findings are about this library's
placeholders until those values are replaced.

| Policy | Placeholder | Stands for |
|---|---|---|
| `images/restrict-image-registries` | `registry.example.com`, `ghcr.io/<your-org>` | Your approved registries and organisation path |
| `images/require-image-signatures` | `registry.example.com/*`, `REPLACE_WITH_YOUR_COSIGN_PUBLIC_KEY` | Your internal registry and signing key |
| `resources/require-topology-spread-constraints` | `resilience.example.com/spread` | The label marking a workload as needing spread |
| `network/require-network-identity-labels` | `network.example.com/tier` | Your network tier label key, and its allowed values |
| `supply-chain/require-build-provenance` | `registry.example.com/*`, `https://github.com/<your-org>/...` | Your registry, signing identity and the builder your provenance declares |
| `supply-chain/require-sbom-attestation` | `registry.example.com/*`, `https://github.com/<your-org>/...` | Your registry, signing identity and banned dependency list |
| `supply-chain/require-recent-vulnerability-scan` | `registry.example.com/*`, `https://github.com/<your-org>/...` | Your registry and signing identity |
| `generate/add-default-network-policies` | `network-baseline.example.com/enabled` | The opt-in namespace label, and the DNS pod labels if the cluster is not a default CoreDNS install |

Everything else means what it says as shipped. The tag policy is registry-agnostic, the
Pod Security Standards are the same in every cluster, and a resource request or a
disruption budget means one thing everywhere.

## Coverage: what is verified, and what is not

| Layer | What it proves |
|---|---|
| `kyverno test` | What Kyverno actually does with a rule, on the pinned CLI version. Every rule of every tested policy is expected to pass somewhere **and** fail somewhere, because a rule only ever expected to pass reports the same result as one that matches nothing. |
| The suite gate | That the above is still true. `kyverno test` says nothing about a rule nobody wrote an expectation for, so coverage can be lost without a run turning red. |
| One admissible workload | That the validating rules are collectively satisfiable. Per-rule cases check rules in isolation and cannot see a pair that together leaves nothing admissible. |
| `yamllint` | That everything parses. |

Four policies are **not** exercised by the CLI, and are named as such in the gate rather
than quietly assumed covered:

| Not tested | Why |
|---|---|
| `images/require-image-signatures` | Reaching a verdict means contacting a registry and checking a signature. That needs a signed image published where the test can read it, not a YAML fixture. |
| `supply-chain/require-build-provenance` | Needs a signed provenance statement attached to a real image. |
| `supply-chain/require-sbom-attestation` | Needs a signed CycloneDX document attached to a real image. |
| `supply-chain/require-recent-vulnerability-scan` | Needs a signed scan attestation, and its conditions are time-relative, so a fixture would expire. |

That gap is real rather than covered. Those rules are exercised by review and by the
structural checks, and the way to close it is a signed test image published from this
repository, at which point `kyverno test --registry` can reach a verdict.

Also deliberately untested: the namespace exclusions (an excluded resource produces no
verdict at all, so an expectation would assert the absence of a result rather than
anything about the rule), the generate set's negative direction (the same shape), and
whether the registry rule resolves identically under an auto-generated rule, which is a
separate question from whether generation happens.

## What this catalog deliberately does not do

It does not map rules to CIS Kubernetes Benchmark or NSA/CISA control identifiers. A
mapping is a promise about a specific benchmark version against a specific distribution,
and one that has silently drifted is worse than none, because it is read as assurance.
Every policy carries `policies.kyverno.io/category` and `policies.kyverno.io/severity`,
and a report tool can group on those without anyone claiming a certification this library
has not earned.
