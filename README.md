# kyverno-policy-library

A curated library of [Kyverno](https://kyverno.io) admission policies for Kubernetes,
organised by the thing each set protects: what images may run, how Pods must be
configured, what they may consume, and what the supply chain must prove.

Every policy in this library ships in **Audit** mode. A policy library dropped into a
live cluster in Enforce mode is an outage, so nothing here blocks anything until an
operator decides it should.

## What this library covers

| Set | Question it answers | Status |
|---|---|---|
| `policies/images/` | Which images may run, from where, and who signed them | shipped |
| `policies/pod-security/` | How a Pod must be configured to be allowed to run | planned |
| `policies/resources/` | What a workload may consume and how it must be spread | planned |
| `policies/network/` | What network identity a workload must declare | planned |
| `policies/supply-chain/` | What the build must prove about itself | planned |
| `policies/generate/` | What Kyverno should create alongside a workload | planned |

## The failures these policies are written around

An admission policy has a failure mode that ordinary software does not: it can be
accepted by the API server, reported as `Ready`, appear in every dashboard as active,
and match nothing at all. Nothing raises, nothing logs, and the only visible signal is
an absence of findings — which is exactly what a healthy cluster also looks like.

Each policy here is written around a specific instance of that:

| The mistake | Why it is invisible |
|---|---|
| Adding `Deployment` to a rule's `match` block to "also cover controllers" | It **disables** Kyverno's automatic rule generation for Pod controllers, which only runs when a rule matches nothing but `Pod`. Coverage gets narrower, and the policy looks more thorough. |
| Denying Docker Hub with a rule that tests the raw `image` field for `docker.io/` | `image: nginx` never contains that string. It is `docker.io/library/nginx:latest` only after Kyverno normalises it, so the deny-list passes the exact images it exists to stop. |
| Forbidding the `latest` tag | An image with **no** tag resolves to `latest` at pull time, and a rule that only forbids the literal tag admits it. Requiring that a tag is present is a separate rule. |
| Allow-listing a shared public registry by hostname | `ghcr.io` is not an authorisation boundary. Allow-listing the host allows every account's packages on it; the repository path is the part that identifies the owner. |
| Validating `spec.containers` | It misses `initContainers` and `ephemeralContainers`. An ephemeral container is injected into a *running* Pod, runs with that Pod's service account, and slips past any rule that only reads the main list. |

## Conventions every policy follows

- **`ClusterPolicy`, one concern per file, one file per `metadata.name`.**
- **Rules match `Pod` and nothing else**, so Kyverno's auto-generation covers Deployments,
  DaemonSets, StatefulSets, Jobs, CronJobs and ReplicaSets. See
  [Auto-Gen Rules](https://kyverno.io/docs/policy-types/cluster-policy/autogen/).
- **All three container lists are checked** — `containers`, `initContainers` and
  `ephemeralContainers` — with the optional two guarded so an absent list is not a failure.
- **Audit by default**, set per rule via `validate.failureAction`, so the enforcement mode
  of a rule is readable beside the rule rather than at the top of the file.
- **Placeholders only.** Registry hostnames, organisation names and keys are
  `registry.example.com`, `<your-org>` and `REPLACE_WITH_...`. Nothing here is a real
  credential or a real account.
- **Every deviation is written down beside the thing it applies to**, not left to be
  rediscovered from a failing cluster.

## Requirements

- **Kyverno 1.13 or newer.** The library uses the per-rule `validate.failureAction` and
  the `webhookConfiguration` block, both of which replaced policy-level settings that were
  deprecated in 1.13.
- Kubernetes 1.25 or newer, matching Kyverno's own support matrix.
- The [Kyverno CLI](https://kyverno.io/docs/kyverno-cli/) for testing policies before they
  reach a cluster.

### A note on the policy type

Current Kyverno releases introduce CEL-based policy types — `ValidatingPolicy`,
`MutatingPolicy`, `ImageValidatingPolicy` and others — and mark `ClusterPolicy` as
deprecated. This library targets `ClusterPolicy` today for two reasons: it is still
supported, documented and in production use across the versions most clusters run, and
its behaviour is verifiable against stable documentation. When the CEL types are pinned
down here they will be added alongside rather than in place of these, since a policy
library is only useful on the version a cluster is actually running. Kyverno publishes a
[migration guide](https://kyverno.io/docs/guides/migration-to-cel/) for the move.

## Quick start

Apply a set and watch what it would have blocked, without blocking anything:

```sh
kubectl apply -f policies/images/
kubectl get clusterpolicy
kubectl get policyreport -A
```

Check a manifest before it reaches a cluster:

```sh
kyverno apply policies/images/ --resource my-workload.yaml
```

Every value in the shipped policies is a placeholder — the registry hostnames, the
organisation name and the signing key. Replace them before reading the reports, or the
reports will simply list everything. `policies/images/README.md` has the table.

Turn a rule on by changing that rule's `validate.failureAction` from `Audit` to
`Enforce`. Read the policy report first — the report is the rehearsal.

## Repository layout

| Path | Contents |
|---|---|
| `policies/` | The policy sets, one directory per concern |
| `policies/README.md` | How a policy in this library is structured and why |
| `policies/images/` | Image provenance: signatures, registries, tags |
| `policies/images/README.md` | What each image policy catches, and what it does not |
| `.yamllint` | Lint configuration shared by the local checks |
| `LICENSE` | MIT |

## Design principles

1. **Audit first.** Nothing blocks until someone reads a report and decides it should.
2. **Match `Pod`, let Kyverno generate the rest.** Naming a controller kind narrows
   coverage instead of widening it.
3. **Compare normalised values, not the string the user typed.** A registry check that
   reads the raw field cannot see the defaults Kubernetes applies at pull time.
4. **Two rules where one leaves a hole.** Forbidding a bad value and requiring a good one
   are different checks, and shipping only the first is a policy that reports clean.
5. **Say what is not covered.** An excluded namespace, a skipped image reference and a
   cached verification result are all gaps, and each one is written down where it applies.
