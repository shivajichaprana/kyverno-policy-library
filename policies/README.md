# Policy sets

Each directory under `policies/` holds one concern. A directory is applied as a unit —
`kubectl apply -f policies/<set>/` — so every file in it is expected to be a valid
Kyverno policy and nothing else.

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

## Auto-generation

Kyverno generates equivalent rules for Deployments, DaemonSets, StatefulSets, Jobs,
CronJobs, ReplicaSets and ReplicationControllers — but **only when the combination of
`match` and `exclude` names no kind other than `Pod`**.

This is the single easiest way to weaken a policy while believing it has been
strengthened. Adding `Deployment` to the `match` block to "cover controllers too" turns
generation off, and the resulting policy covers Pods and Deployments instead of Pods and
every controller that creates them.

The consequence for this library is a hard convention: **a rule matches `Pod`, or it is
not in this library.** Namespace-based `exclude` blocks are fine; they name no kind.

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
rule with a documented bypass. Every rule in this library covers all three, with the two
optional lists guarded by the `=()` conditional anchor so their absence is not a failure.

## Enforcement modes

`failureAction` is set per rule:

- **`Audit`** — the request is admitted and the result is written to a `PolicyReport`.
  Everything ships this way.
- **`Enforce`** — the request is rejected.

Move a rule to `Enforce` only after its report has been clean for long enough to believe
it. `failureActionOverrides` can raise a single namespace to `Enforce` ahead of the rest,
which is the usual way to prove a rule in one place before turning it on everywhere.

Image verification rules are the exception, and deliberately so: Kyverno documents no
per-rule `failureAction` for `verifyImages`, so those policies still carry the
policy-level `validationFailureAction`. That field is deprecated, its documented
replacement covers `validate` rules only, and the file that uses it says so.

## Testing

Policies are exercised with the Kyverno CLI against manifests that are expected to pass
and manifests that are expected to fail. A policy set without a failing case is not
tested — a rule that matches nothing passes every positive test ever written for it.
