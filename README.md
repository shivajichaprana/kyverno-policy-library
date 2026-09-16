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
| `policies/pod-security/` | How a Pod must be configured to be allowed to run | shipped |
| `policies/resources/` | What a workload may consume and how it must be spread | shipped |
| `policies/network/` | What network identity a workload must declare | shipped |
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
| Writing `runAsNonRoot` or `seccompProfile` as a pattern over `spec.containers[]` | Those fields may be set on the Pod, on the container, or on both, and the container wins. A container-level pattern **fails** a Pod that set the field once at the Pod level and inherits it correctly; a Pod-level pattern **misses** a container that overrides it to `false`. One direction floods the report with false findings, the other reports clean. |
| Turning on the restricted profile and considering the Pod hardened | `readOnlyRootFilesystem` is in neither profile. It was a PodSecurityPolicy field that was not carried into the standards, so a migration from PSP loses it and nothing reports the absence of a rule. |
| Excluding a Pod Security control with one `exclude[]` entry | A control with restricted fields at **both** the `spec` and `containers[]` levels needs **two** entries. One excludes half of it, the other half keeps rejecting, and the exclusion looks applied — so the investigation starts in the wrong place. |
| Requiring `resources` on all three container lists, for consistency | The API forbids `resources` on an ephemeral container. The rule describes a Pod that cannot be submitted, so it can never pass, and its whole output is a finding against every `kubectl debug` session. |
| Writing `maxUnavailable: 0` in a PodDisruptionBudget | It is accepted, healthy and visible in `kubectl get pdb`. The first symptom is a node drain that never finishes, during an upgrade somebody scheduled for a maintenance window. |
| Leaving a PodDisruptionBudget's `selector` empty | On `policy/v1` an empty selector covers **every pod in the namespace**. On the `policy/v1beta1` API it covered none. The same manifest reversed its meaning across the upgrade that removed that version. |
| Declaring `topologySpreadConstraints` and checking the field is present | `labelSelector` is optional, and without it the constraint counts no pods and is satisfied by any placement. The field is there, the check passes, and no scheduling decision is ever affected. |
| Setting `whenUnsatisfiable: ScheduleAnyway` to avoid Pending pods | It converts a visible failure into an invisible one. The scheduler discards the constraint when it cannot be met, so the workload declares spreading and still runs every replica on one node. |
| Requiring a network label but not its value | `tier: frontned` is a valid label. The Pod runs, the presence check passes, and it is selected by no NetworkPolicy written for `frontend`. |

## Conventions every policy follows

- **`ClusterPolicy`, one concern per file, one file per `metadata.name`.**
- **No rule names `Pod` alongside another kind**, so Kyverno's auto-generation covers
  Deployments, DaemonSets, StatefulSets, Jobs, CronJobs and ReplicaSets. See
  [Auto-Gen Rules](https://kyverno.io/docs/policy-types/cluster-policy/autogen/). A rule
  whose subject is not a Pod — a PodDisruptionBudget, say — matches that kind alone and
  loses nothing: there is no pod template, so there is no rule to generate.
- **All three container lists are checked** — `containers`, `initContainers` and
  `ephemeralContainers` — with the optional two guarded so an absent list is not a failure.
  This applies to every rule that enumerates containers itself, except where the field
  being required cannot legally be set on all three: `resources` is forbidden on an
  ephemeral container, so requiring it there would be a rule that can never pass. A
  `podSecurity` subrule names no list because it does not iterate one: it hands the Pod to
  the same library Pod Security Admission uses, which already reads all three.
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

Four policies need editing before their reports mean anything, because a registry, an
organisation, a signing key or a label key in them stands in for one of yours:

| Policy | What to substitute | Table |
|---|---|---|
| `policies/images/restrict-image-registries.yaml` | Registry hostnames and the organisation path | [`policies/images/README.md`](policies/images/README.md) |
| `policies/images/require-image-signatures.yaml` | Registry hostname and the signing key | [`policies/images/README.md`](policies/images/README.md) |
| `policies/resources/require-topology-spread-constraints.yaml` | The label marking a workload as needing spread | [`policies/resources/README.md`](policies/resources/README.md) |
| `policies/network/require-network-identity-labels.yaml` | The network tier label key and its allowed values | [`policies/network/README.md`](policies/network/README.md) |

The rest mean what they say as shipped. The tag policy is registry-agnostic; the Pod
Security Standards are the same everywhere; and a resource request or a disruption budget
means the same thing in every cluster.

Turn a rule on by changing that rule's `validate.failureAction` from `Audit` to
`Enforce`. Read the policy report first — the report is the rehearsal.

## Repository layout

| Path | Contents |
|---|---|
| `policies/` | The policy sets, one directory per concern |
| `policies/README.md` | How a policy in this library is structured and why |
| `policies/images/` | Image provenance: signatures, registries, tags |
| `policies/images/README.md` | What each image policy catches, and what it does not |
| `policies/pod-security/` | Pod configuration: the Pod Security Standards, immutable root filesystem |
| `policies/pod-security/README.md` | Why these are a `podSecurity` subrule, and how to adopt them |
| `policies/resources/` | Consumption and placement: requests and limits, disruption budgets, topology spread |
| `policies/resources/README.md` | The request/limit asymmetry, the budgets that block every drain, and what spreading does not check |
| `policies/network/` | Network identity: the labels a NetworkPolicy selects on |
| `policies/network/README.md` | Why this checks labels rather than NetworkPolicies, and what it cannot see |
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
6. **Never re-check what the API already rejects.** A rule that can only fire on a request
   the API server refuses to accept cannot fire at all, and a rule that never fires is
   indistinguishable in a report from one that is working.
