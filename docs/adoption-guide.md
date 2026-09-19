# Adoption guide

How to get from "the policies are applied" to "the policies are enforced" without an
outage in the middle.

The library ships entirely in Audit for a reason that is worth stating before the steps:
an admission policy in Enforce mode is a change to what the API server accepts, and the
workloads it will reject are the ones that already exist. The order below exists to make
every rejection something somebody has already read in a report.

## The order, and why it is an order

```
install  →  apply (nothing blocks)  →  read the report  →  substitute  →  fix or except  →  enforce one rule
```

Each step is a precondition for the next, not a suggestion:

- **Applying before reading** is safe here, because nothing is in Enforce. This is the only
  step that can be done without preparation.
- **Reading before substituting** tells you which findings are about your cluster and which
  are about this library's example registry. Substituting first hides that distinction.
- **Substituting before fixing** stops work being done against placeholder values.
- **Fixing before enforcing** is the whole point. A rule moved to Enforce with a non-empty
  report is a rule that will reject a redeploy of something already running.

## Phase 0 — install and apply

Kyverno 1.13 or newer, on Kubernetes 1.25 or newer. The library uses the per-rule
`failureAction` fields, which replaced the policy-level settings deprecated in 1.13.

```sh
kubectl apply -f policies/images/
kubectl apply -f policies/pod-security/
kubectl apply -f policies/resources/
kubectl apply -f policies/network/
kubectl get clusterpolicy
```

Every policy should show `Ready`. `Ready` means Kyverno accepted it, and nothing more —
it is not evidence that the policy matches anything, which is the failure mode the whole
library is written around.

Hold back two sets at this stage:

- **`policies/supply-chain/` and `require-image-signatures`** contact a registry to reach
  a verdict. Applying them before the registry credentials exist produces findings about
  connectivity rather than about images. See [Image verification](#image-verification-the-set-with-a-dependency).
- **`policies/generate/`** creates resources rather than reporting on them, and is armed
  separately. See [The generate set](#the-generate-set-armed-separately).

Before any of this reaches a cluster, the same policies can be run against a manifest:

```sh
make apply RESOURCE=my-workload.yaml
```

## Phase 1 — read the report

```sh
kubectl get policyreport -A
kubectl get clusterpolicyreport
kubectl get policyreport -n my-namespace -o yaml | less
```

A `PolicyReport` exists per namespace and holds one result per resource per rule. The
count that matters first is not the total but the spread: a rule failing on nearly
everything is usually a placeholder, and a rule failing on nothing at all deserves a
moment's suspicion before it is called clean.

Every finding is one of three things, and
[the catalog](policy-catalog.md#reading-a-finding) says how to tell them apart. Work
through them in that order — placeholders first, because substituting changes which
findings remain.

## Phase 2 — substitute

Eight policies carry an example registry, organisation, key or label key. The full list is in
[the catalog](policy-catalog.md#substitution-the-rules-that-are-inert-until-edited), and
each set README has the detail for its own.

The substitutions are not cosmetic. Two of them change what the rule means:

- **The network tier label key and its allowed values.** The value list is the rule. A
  cluster using `tier: web` rather than `frontend` will see every Pod fail the value check
  until the list matches its own vocabulary.
- **The registry allow-list and repository path.** The repository path is the part that
  identifies a publisher; leaving a shared public registry allow-listed by hostname alone
  admits every account on it.

Re-apply and read the report again. What remains is about your cluster.

## Phase 3 — fix, or make the exception explicit

Three ways to remove a finding, in descending order of preference:

**Fix the workload.** The rule's `message` says what to change, and it is written to be
actionable rather than to restate the rule name.

**Grant a `PolicyException`.** For a workload that genuinely cannot comply — a monitoring
agent that needs a host path, a CI runner that needs a writable root filesystem. An
exception is a reviewable object with a name and a namespace, which is its advantage over
the alternative:

```yaml
apiVersion: kyverno.io/v2
kind: PolicyException
metadata:
  name: node-exporter-host-access
  namespace: monitoring
spec:
  exceptions:
    - policyName: require-pod-security-standards
      ruleNames:
        - validate-baseline-profile
  match:
    any:
      - resources:
          kinds:
            - Pod
          namespaces:
            - monitoring
          names:
            - node-exporter-*
```

Two things about exceptions are worth knowing before the first one is written, because
both fail quietly. `PolicyException` is **off by default** — Kyverno's `enablePolicyException`
flag defaults to false, so an exception applied to a default installation is accepted as an
object and consulted by nothing. And the namespaces exceptions may live in are controlled by
`exceptionNamespace`, which is empty by default and accepts `*` for all of them. Point it at
a namespace that requires review to write to, rather than at the namespace the exception
applies to — otherwise the team being excepted grants its own exception.

The `kyverno.io/v2` exception above is the one that applies to a `ClusterPolicy`. Current
Kyverno marks it deprecated alongside `ClusterPolicy` itself, in favour of the
`policies.kyverno.io` type that pairs with the CEL policies; the two migrate together, not
separately.

**Except a single Pod Security control.** The profile rules take a third route the others
do not, and it is better than both editing the policy and excepting the whole rule: a
`PolicyException` carries its own `podSecurity` block, so one control can be lifted for one
workload while the rest of the profile keeps applying.

```yaml
spec:
  exceptions:
    - policyName: require-pod-security-standards
      ruleNames:
        - validate-restricted-profile
  podSecurity:
    - controlName: Capabilities
      images:
        - "registry.example.com/network-agent:*"
```

Editing the policy's own `exclude` block is the blunter alternative, and it has a trap: a
control with restricted fields at **both** the `spec` and `containers[]` levels needs **two**
entries. One entry excludes half of it, the other half keeps rejecting, and the exclusion
looks applied — so the investigation starts in the wrong place.
[`policies/pod-security/README.md`](../policies/pod-security/README.md) has the worked
example.

What none of these should be is editing the rule to stop catching the thing. A rule
narrowed until it reports clean is indistinguishable from a rule that works.

## Phase 4 — enforce, one rule at a time

Change that rule's `failureAction` from `Audit` to `Enforce`. Not the file, not the set —
the rule. Each is independent, which is why they are written as separate rules.

A suggested order, worst-consequence-if-wrong last:

| Order | Rule | Why here |
|---|---|---|
| 1 | `disallow-mutable-image-tags` (both rules) | The cheapest to comply with and the easiest to verify. Nothing needs infrastructure to exist first. |
| 2 | `require-resource-requests-and-limits` | Widely violated, trivially fixable, and the fix improves scheduling immediately. Expect the largest number of findings here. |
| 3 | `require-network-identity-labels` | Labels only. No behaviour changes when a workload complies. |
| 4 | `require-safe-disruption-budgets` | Rejects a configuration that would block a drain. Few objects, high consequence if one slips through. |
| 5 | `require-pod-security-standards` / baseline | The first rule that rejects a running workload's shape rather than its metadata. Enforce baseline; leave restricted in Audit. |
| 6 | `restrict-image-registries` | Enforcing this without every registry in the allow-list stops deployments, including rollbacks. Confirm the report is empty across every namespace, not just the busy ones. |
| 7 | `require-read-only-root-filesystem` | Frequently needs a volume added to the workload, so the fix is a real change rather than a field. |
| 8 | `require-pod-security-standards` / restricted | The hardest, and the one worth arriving at deliberately. |
| 9 | `require-topology-spread-constraints` | `require-enforced-spread` will reject `ScheduleAnyway`, which some workloads choose on purpose. Read the set README's argument before enforcing this one. |

Two rules are not on the list because they are governed by something other than their
own readiness: `require-image-signatures` needs the registry work below, and the
supply-chain rules need attestations to exist before they can pass.

After each change, watch for rejections rather than assuming there will be none:

```sh
kubectl get events -A --field-selector reason=PolicyViolation
```

Rolling one back is the same edit in reverse, and it takes effect immediately. That is
the argument for one rule at a time — a batch of six leaves you guessing which one to
revert while deployments are failing.

## Image verification: the set with a dependency

`require-image-signatures` and the three `supply-chain` policies verify signatures and
attestations, which means a registry round trip on every admission. Three consequences
follow, and all three are easier to plan for than to discover:

**They do not run in background scans.** `background: false`, because a background scan
carries no pull secrets from the original request and would reach a private registry
unauthenticated. Findings appear on admission only, so an existing workload produces
nothing until it is redeployed.

**Verification results are cached.** Kyverno caches a verification for 60 minutes by
default. Revoking a key is not effective for up to an hour, and nothing reports that it
is not yet effective.

**`failurePolicy: Fail` chooses which outage you get.** With `Fail`, a Kyverno outage
blocks admission. With `Ignore`, a **registry** outage admits unverified images. There is
no setting that is safe in both directions; the library ships `Fail` with a 30-second
timeout, which is the choice that fails closed.

One coupling to plan for when enforcing: `mutateDigest` rewrites a verified tag to its
digest, and Kyverno refuses that setting while the failure action is `Audit`. The rewrite
therefore becomes available at the same moment the rule starts blocking — and it is a
permanent diff against a GitOps reconciler, which needs telling to ignore the image field
before the change lands.

## The generate set: armed separately

This set has no audit mode. A generate rule creates its resource or it does not, so there
is no rehearsal mode to sit in and the safety is entirely in the match condition.

Three things must be true in this order:

**1. The RBAC exists.** Without it the policy is accepted, reports `Ready`, and creates
nothing. There is no admission failure to see, because generation does not happen during
admission.

```sh
kubectl apply -f policies/generate/background-controller-rbac.yaml
```

**2. The CNI enforces NetworkPolicy.** On a cluster whose CNI ignores them, every resource
is created correctly and enforces nothing — and `kubectl get networkpolicy -A` looks
identical either way. Confirm with the CNI's own documentation, not by looking at the
objects.

**3. One namespace is labelled, and it is not production.**

```sh
kubectl label namespace sandbox network-baseline.example.com/enabled=true
kubectl get networkpolicy -n sandbox
```

Both policies should appear. Then confirm the thing that actually breaks: name
resolution.

```sh
kubectl run dnstest --rm -it --image=registry.example.com/busybox:1.36 \
  -n sandbox --restart=Never -- nslookup kubernetes.default
```

A deny-all egress policy blocks DNS, and the symptom — applications failing to reach
things by name — reads as an application fault rather than a network policy. That is why
the DNS exception is generated alongside rather than afterwards, and why it is worth
proving before the second namespace is labelled.

`generateExisting` is set so that namespaces created before the policy are covered too.
Left at its default, only namespaces created afterwards get anything: every existing
namespace stays unprotected, and because no rule was triggered for them, no gap is
reported.

Removing the label removes the generated policies, because the rules are synchronised. In
a namespace that has come to depend on the DNS exception, that is a connectivity change —
so label removal is an operation, not a cleanup.

## Upgrades

**The Pod Security Standards track the Kyverno version.** The profile rules use
`version: latest`, so the meaning of the rule can change on a Kyverno upgrade rather than
on a commit. That is right for a rule in Audit and wrong for one in Enforce — pin the
version before enforcing, so an upgrade cannot start rejecting workloads without a change
to this repository.

**Everything else is pinned.** The CLI version used by the pipeline is pinned, the action
SHAs are pinned, and the policy constructs that are version-dependent are named in the
workflow beside the pin.

## Removing the library

```sh
kubectl delete -f policies/images/ -f policies/pod-security/ \
  -f policies/resources/ -f policies/network/
```

The generate set is the one that needs thought, because deleting a generate policy
normally takes every resource it generated with it — and for a deny-all rule that means
opening the network in every labelled namespace at the same moment. This library sets
`orphanDownstreamOnPolicyDelete: true` so that does not happen: deleting the policy
**leaves** the NetworkPolicies in place.

That is the better half of the trade rather than a free win. The generated policies keep
enforcing and are no longer reconciled by anything, so they have to be removed by hand
when they are genuinely no longer wanted:

```sh
kubectl delete -f policies/generate/
kubectl get networkpolicy -A -l network-baseline.example.com/generated=true
```

To take a single namespace out while the policy is still in place, remove its label
instead. The rules are synchronised, so Kyverno deletes the generated policies with it —
which for a namespace that has come to rely on the DNS exception is a connectivity change,
not a cleanup. One namespace at a time, confirmed before the next.

`PolicyException` objects survive too. They name a policy that no longer exists and become
inert, which is harmless but misleading to whoever reads them next.
