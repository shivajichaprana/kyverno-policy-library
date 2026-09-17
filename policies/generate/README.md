# Generate policies

One policy, and the permission without which it does nothing.

| File | Kind | What it does |
|---|---|---|
| `add-default-network-policies.yaml` | `ClusterPolicy` | Creates a deny-all NetworkPolicy covering both directions, and the DNS egress exception that keeps the namespace usable, in every namespace carrying the opt-in label |
| `background-controller-rbac.yaml` | `ClusterRole` | Grants Kyverno's background controller permission to create those NetworkPolicies. Without it the policy above is accepted, reported healthy, and creates nothing. |

| Policy | Rules | What it catches |
|---|---|---|
| `add-default-network-policies.yaml` | `add-deny-all`, `add-dns-egress` | A namespace with no network baseline at all — every pod in it reachable from every pod in the cluster, which is the Kubernetes default and looks exactly like a working cluster |

## Before applying these

| Replace | In | With |
|---|---|---|
| `network-baseline.example.com/enabled` | `add-default-network-policies.yaml` | The label key you want to opt a namespace in with |
| `k8s-app: kube-dns` | `add-default-network-policies.yaml` | The labels your cluster's DNS pods actually carry, if it is not a default CoreDNS install |

```sh
kubectl apply -f policies/generate/
kubectl get clusterrole kyverno:background-controller -o yaml | grep -A3 networkpolicies
kubectl label namespace <namespace> network-baseline.example.com/enabled=true
kubectl get networkpolicy -n <namespace>
```

The second command is not optional. It is how you find out whether the grant aggregated,
and it is the difference between this working and this reporting that it works.

## This set has no audit mode

Everything else in this library reports and blocks nothing. A generate rule has neither
setting: it creates the resource or it does not, and `failureAction` does not apply to it.

So the safe default is expressed differently. The rules match only namespaces carrying the
opt-in label, which means that as shipped they act on nothing. Labelling a namespace is the
deliberate act, and it is reversible one namespace at a time.

That is not caution for its own sake. A deny-all NetworkPolicy arriving in a namespace
whose workloads are already running severs them immediately, and a policy that matched
every namespace would do it everywhere at once.

## Four ways this creates nothing while looking correct

| The situation | What you see |
|---|---|
| The background controller has no RBAC | `kubectl get clusterpolicy` shows the policy Ready. No NetworkPolicy is ever created. Nothing fails, because generation does not happen during admission and there is no admission failure to report. |
| `generateExisting` is left at its default of `false` | Only namespaces created after the policy get anything. Every namespace that already existed stays unprotected, and no rule was triggered for them, so no gap is reported. |
| The CNI does not implement NetworkPolicy | Every resource is created correctly and enforces nothing. `kubectl get networkpolicy -A` is identical either way. This is the case where all the evidence is present and none of it is true. |
| Only one direction is named in `policyTypes` | A resource called `default-deny` is present in every namespace with ingress entirely unrestricted. The name is doing the work the spec is not. |

The first two are handled in the files. The third cannot be — confirm it before believing
any of this. The fourth is what the `policyTypes` list in `add-deny-all` is about.

## Why DNS is generated alongside, not afterwards

Deny-all egress blocks name resolution, because resolution is egress to kube-dns. Every
lookup in the namespace fails, and the symptom is applications failing to reach things by
name — which reads as an application fault and sends the investigation to the wrong team.

The two rules are in one file so the deny cannot be applied without the exception that
makes it survivable. The allowance covers UDP **and** TCP on 53: DNS falls back to TCP for
responses too large for a datagram, so a UDP-only allowance works for most queries and
fails for some, which is harder to diagnose than a total failure.

### The hyphen that widens the rule

In a NetworkPolicy peer list, two selectors in the **same** list item mean AND; in
**separate** items they mean OR.

```yaml
# AND — kube-dns pods, in kube-system. What the policy says.
to:
  - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
    podSelector: {matchLabels: {k8s-app: kube-dns}}

# OR — every pod in kube-system, or any pod labelled k8s-app=kube-dns anywhere.
to:
  - namespaceSelector: {matchLabels: {kubernetes.io/metadata.name: kube-system}}
  - podSelector: {matchLabels: {k8s-app: kube-dns}}
```

One hyphen. Both parse, both are valid, and the second grants a great deal more than the
first while reading almost identically in a diff.

## Lifecycle

| Setting | Value here | What it means |
|---|---|---|
| `synchronize` | `true` | An edited or deleted generated policy is put back. Without it a namespace silently loses its baseline and the only evidence is an absence. |
| `orphanDownstreamOnPolicyDelete` | `true` | Deleting this ClusterPolicy leaves the generated NetworkPolicies in place. The default, `false`, removes every one of them across every namespace at once — for a deny rule, that means uninstalling the policy opens the network everywhere. |

The cost of orphaning is real: nothing reconciles those policies afterwards and they have
to be cleaned up by hand. For a control whose failure direction is open, that is the
better half of the trade.

## What this set does not do

- **It does not write application policy.** A deny-all plus DNS is a floor. Everything a
  workload is actually allowed to reach is a NetworkPolicy the owning team writes, and
  those are selected by the labels `policies/network/` requires.
- **It does not allow intra-namespace traffic.** A multi-service namespace needs its own
  allowance; that decision belongs with whoever knows which services talk to each other.
- **It does not remove a baseline when a namespace is un-labelled** unless synchronization
  removes it. Check rather than assume, and remember that orphaning is on.
- **It does not verify that the DNS selector matches anything.** A selector matching no pod
  produces an allowance that permits nothing while appearing to permit DNS.
