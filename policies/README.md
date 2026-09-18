# Policy sets

Each directory under `policies/` holds one concern. A directory is applied as a unit —
`kubectl apply -f policies/<set>/` — so a file in it is a Kyverno policy unless the
policies in that set cannot function without it.

There is one such file, and the test that admits it is narrow: `policies/generate/` ships
the ClusterRole granting Kyverno's background controller permission to create the
resources its rules generate. Without that grant the policy is accepted, reported healthy,
and creates nothing at all. Keeping the grant in a separate tree would make the directory
that looks self-contained the one that silently does nothing — the exact failure this
library is written to avoid, reproduced in its own layout.

## Structure of a policy in this library

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: <one-concern-per-name>
  annotations:
    policies.kyverno.io/title: <human-readable title>
    policies.kyverno.io/category: <set name>
    policies.kyverno.io/severity: <low|medium|high>
    policies.kyverno.io/subject: Pod
    policies.kyverno.io/description: >-
      What the policy does, and what it deliberately does not do.
spec:
  background: true
  rules:
    - name: <verb-noun>
      match:
        any:
          - resources:
              kinds:
                - Pod          # Pod and nothing else — see "Auto-generation" below
      exclude:
        any:
          - resources:
              namespaces:      # namespaces, never kinds
                - kube-system
      validate:
        failureAction: Audit   # per-rule, so the mode is readable beside the rule
        message: >-
          What was rejected and what to do instead.
        pattern: {}
```

A rule uses `deny` with conditions instead of `pattern` where a pattern cannot express the
check. The two cases that come up here are set membership — a label whose value must be
one of several — and emptiness: a pattern can require that a key is present, but not that
a map beneath it has at least one entry. Both appear in `policies/resources/` and
`policies/network/`, and each one says beside itself why it is not a pattern.

## Auto-generation

Kyverno generates equivalent rules for Deployments, DaemonSets, StatefulSets, Jobs,
CronJobs, ReplicaSets and ReplicationControllers — but **only when the combination of
`match` and `exclude` names no kind other than `Pod`**.

This is the single easiest way to weaken a policy while believing it has been
strengthened. Adding `Deployment` to the `match` block to "cover controllers too" turns
generation off, and the resulting policy covers Pods and Deployments instead of Pods and
every controller that creates them.

The consequence for this library is a hard convention: **no rule ever names `Pod`
alongside another kind.** Namespace-based `exclude` blocks are fine; they name no kind.

A rule whose subject is not a Pod matches that kind alone, and loses nothing by it. A
PodDisruptionBudget carries no pod template, so there is no equivalent rule for a
controller to generate; auto-generation has nothing to do and its absence costs nothing.
The combination that silently narrows coverage is `Pod` plus something else, and that is
the one the convention forbids.

It also changes where a rejection surfaces. With generation on, a bad Deployment is
refused at `kubectl apply`. With it off, the Deployment is accepted and its ReplicaSet
fails to create Pods, so the workload sits at zero replicas and the reason is an event on
a resource the author did not create.

## Container lists

A Pod spec has three lists of containers, and only one of them is mandatory:

| List | Present when | Why it matters |
|---|---|---|
| `containers` | always | The workload |
| `initContainers` | optional | Runs first, with the same access to images and volumes |
| `ephemeralContainers` | injected later | Added to a **running** Pod by `kubectl debug`, with that Pod's service account and namespace |

A rule that reads only `containers` is not a weaker version of a complete rule — it is a
rule with a documented bypass. Rules in this library cover all three, with the two
optional lists guarded by the `=()` conditional anchor so their absence is not a failure.

There is one real exception, and the test that produces it is worth stating as the rule
itself: **can the field being required legally be set on all three?** `resources` cannot.
The API forbids it on an ephemeral container, because a Pod's allocation is fixed when the
Pod is admitted and an ephemeral container joins one that is already running. A rule
requiring it there would describe a Pod the API server rejects — it could never pass, and
its only output would be a finding against every `kubectl debug` session. So
`policies/resources/` covers two lists, deliberately, and says so where it does it.

A `podSecurity` subrule names no list for a different reason: it does not iterate one. It
hands the Pod to the same library Pod Security Admission uses, which already reads all
three.

## Enforcement modes

`failureAction` is set per rule:

- **`Audit`** — the request is admitted and the result is written to a `PolicyReport`.
  Everything ships this way.
- **`Enforce`** — the request is rejected.

Move a rule to `Enforce` only after its report has been clean for long enough to believe
it. `failureActionOverrides` can raise a single namespace to `Enforce` ahead of the rest,
which is the usual way to prove a rule in one place before turning it on everywhere.

A **generate** rule has no audit mode, and no enforce mode either. It creates the resource
or it does not, and there is no setting that makes it describe what it would have created. The equivalent safe default
is a match condition that starts empty: `policies/generate/` acts only on namespaces
carrying an opt-in label, so as shipped it acts on nothing and is turned on one namespace
at a time.

Image verification rules set their mode the same way, on `verifyImages[*]` rather than on
`validate`. Nothing in this library uses the policy-level `validationFailureAction`, which
is deprecated, and a test asserts that no file reintroduces it.

There is one control that `Audit` makes unavailable rather than merely unenforced.
`verifyImages[*].mutateDigest` rewrites a verified tag to the digest it resolved to, and
Kyverno refuses the combination: with an `Audit` failure action the policy is rejected on
admission and by `kyverno apply`. So the rewrite is not a separate decision to take later
— it is part of moving an image-verification rule to `Enforce`.

## Attestation rules

A `verifyImages` rule carrying an `attestations` block has one optional part that does all
the work. `attestors` is required and pins **who signed** the statement. `conditions` is
optional and is the only part that pins **what the statement says** — so a rule with
attestors and no conditions verifies that a correctly signed document of the right type
exists, and nothing whatever about its contents.

Every attestation rule in this library carries conditions, and every condition key uses a
`|| ''` fallback. That is not defensive padding: an unresolvable variable makes Kyverno
report a rule **error** rather than a rule failure, and an error reads as the admission
controller being broken rather than the image failing a check, which sends whoever picks
up the finding to the wrong place.

## Testing

Policies are exercised with the Kyverno CLI against manifests that are expected to pass
and manifests that are expected to fail. A policy set without a failing case is not
tested — a rule that matches nothing passes every positive test ever written for it.
