# Network policies

One policy covering the labels a NetworkPolicy needs in order to find a Pod.

| Policy | Rules | What it catches |
|---|---|---|
| `require-network-identity-labels.yaml` | `require-identity-labels`, `require-known-network-tier` | A Pod no NetworkPolicy can select, and a tier value no NetworkPolicy was written for |

## Before applying these

| Replace | In | With |
|---|---|---|
| `network.example.com/tier` | `require-network-identity-labels.yaml` | The label key your NetworkPolicies select on |
| `frontend`, `backend`, `data`, `egress-restricted` | `require-network-identity-labels.yaml` | The tiers your cluster actually has |

`app.kubernetes.io/name` is a standard Kubernetes label and is left as it is.

```sh
kubectl apply -f policies/network/
kubectl get policyreport -A
```

## Why labels and not NetworkPolicies

A NetworkPolicy does not name workloads. It selects them, by label, and a Pod carrying the
wrong labels is simply not selected — with nothing reported anywhere, because the
NetworkPolicy is valid, present and doing exactly what it says.

Which direction that fails in depends on something the Pod cannot see:

| The namespace has | An unlabelled Pod gets | How it is found |
|---|---|---|
| A default-deny policy | No connectivity it was not granted | Immediately. The workload cannot reach anything and somebody fixes it within the hour. |
| No default-deny policy | **No restrictions at all** | It is not found. A Pod selected by no NetworkPolicy is unrestricted, and the cluster looks exactly as it does when everything is correct. |

The second row is the reason this policy exists.

## The typo is the interesting case

`tier: frontned` is a valid label. The API accepts it, the Pod runs, and it is selected by
no NetworkPolicy written for `frontend`.

That makes presence-checking the weaker half of the job, so the two rules are split:

| Rule | Reports | Fix |
|---|---|---|
| `require-identity-labels` | The label is missing | Add it |
| `require-known-network-tier` | The label holds a value no policy was written for | Correct it, or add the tier to the allowed set and write policy for it |

A single rule covering both would report one finding for two problems with different
fixes. The precondition on the second rule is what keeps a missing label from being
counted twice — it judges the value only when there is one.

The sentinel in that precondition is `<absent>`, chosen because Kubernetes label values
may hold only alphanumerics, `-`, `_` and `.`. Angle brackets are rejected by the API, so
no real label can equal it and the guard cannot be defeated by a workload that sets the
value to whatever the sentinel happens to be.

## What this does not do

It does not check that a NetworkPolicy selecting each tier exists, and it cannot: an
admission rule sees one object, and whether some *other* object selects it is a question
about the whole namespace. Labelling every Pod correctly in a namespace with no
NetworkPolicy at all produces a perfectly clean report and an entirely open network.

The labels are a precondition for network policy, not a substitute for it. The other half
is a namespace-level report — this, run against the namespaces that hold workloads, is the
shortest version of it:

```sh
kubectl get networkpolicy -A
```

A namespace with workloads and no rows is the case to look at first.

Nor can it tell whether the tier a workload claims is the right one. A database that
labels itself `frontend` is consistent, selectable, and wrong.
