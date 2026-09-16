# Resource policies

Three policies covering what a workload is allowed to consume and where its replicas are
allowed to land.

| Policy | Rules | What it catches |
|---|---|---|
| `require-resource-requests-and-limits.yaml` | `require-resource-requests`, `require-memory-limits` | A container the scheduler has been told needs nothing, or one bounded only by the node |
| `require-safe-disruption-budgets.yaml` | `disallow-blocking-budgets`, `require-explicit-budget-selector` | A budget that can never permit an eviction, or one that does not say what it protects |
| `require-topology-spread-constraints.yaml` | `require-spread-label-selector`, `require-enforced-spread`, `require-spread-for-labelled-workloads` | A spread constraint that is declared and has no effect on any scheduling decision |

## Before applying these

One value needs substituting, and only for the third policy:

| Replace | In | With |
|---|---|---|
| `resilience.example.com/spread` | `require-topology-spread-constraints.yaml` | The label your cluster uses to mark a workload as needing spread |

The first two policies carry no placeholders. Resource requests and disruption budgets
mean the same thing in every cluster, so applied unchanged they produce a true report.

```sh
kubectl apply -f policies/resources/
kubectl get policyreport -A
```

## Resource requests and limits

The shipped position is **request both, limit memory**, and the asymmetry is deliberate.

| Resource | Over its request | Missing limit costs |
|---|---|---|
| Memory | Cannot be throttled, only killed | Other workloads — the node fills, the kubelet evicts neighbours |
| CPU | Throttled | Itself — and a CPU limit adds throttling even on an idle node |

That is a position rather than a fact. A cluster that bills by limit, or that needs each
workload to perform identically whatever else is running, has good reason to require CPU
limits too; add a third rule if that is your cluster. The mistake worth avoiding is
requiring all four without deciding, and meeting the throttling months later in a latency
graph.

### The exception to the three-container-list convention

Every other container-level rule in this library covers `containers`, `initContainers`
and `ephemeralContainers`. This one covers two, because **the Kubernetes API does not
permit `resources` on an ephemeral container at all** — a Pod's resource allocation is
fixed when it is admitted, and an ephemeral container is added to a Pod that is already
running, so it is given nothing of its own and runs inside what the Pod already holds.

Requiring the field there would describe a Pod the API server will not accept: the rule
could never pass, and its only possible output is a finding against every `kubectl debug`
session anybody runs.

The check to apply when adding a container-level rule is therefore not *did I list all
three* but **can this field legally be set on all three**.

### What a clean report does not tell you

The rule reads the Pod as it reaches the admission webhook, which is not necessarily the
Pod the author wrote. Where a namespace has a `LimitRange` supplying defaults, this rule
sees the defaulted values and reports the Pod as compliant — the right verdict, since
those values are real and will be enforced, but not evidence that anybody chose them. The
place to see what was chosen is the manifests in source control.

It also accepts any declared number. A request of `1m` CPU is a declaration.

## Disruption budgets

A PodDisruptionBudget is the one object in a cluster whose failure mode is working too
well. Three ways to write one that permits nothing:

| Written | Effect | Caught here |
|---|---|---|
| `maxUnavailable: 0` | No pod may be evicted, ever | yes |
| `minAvailable: 100%` | The same statement, the other way round | yes |
| `minAvailable` equal to the replica count | The same effect again | **no** — the replica count is not in the budget |

None of the three is rejected by the API, because all three are legitimate things to say
briefly while something is being migrated. Left in a manifest they are a cluster that
cannot be drained: `kubectl drain` waits for a disruption the cluster has been told never
to permit.

The third is not detectable from the budget alone. The value that covers every case
including it is the cluster's own arithmetic:

```sh
kubectl get pdb -A -o custom-columns=\
NS:.metadata.namespace,NAME:.metadata.name,ALLOWED:.status.disruptionsAllowed
```

Anything sitting at `0` in steady state will block a drain.

### The selector that reversed meaning

`spec.selector: {}` is the quietest of these.

| Selector | `policy/v1` | `policy/v1beta1` (removed in 1.25) |
|---|---|---|
| `{}` | Selects **every pod in the namespace** | Selected none |
| unset | Selects none | Selects none |
| `matchLabels: {app: web}` | Selects that workload | The same |

The same manifest, unchanged and still valid, reversed its meaning across the upgrade
that stopped serving `v1beta1` — from a budget that protected nothing to one that governs
everything beside it. `require-explicit-budget-selector` treats the empty selector and the
unset selector as one finding, because in both cases the budget does not say what it
covers and the consequence depends on a server version rather than on the document.

## Topology spread

The rules validate the constraints a workload declares. They do **not** require every Pod
to declare one, and that is a deliberate limit: a single-replica Pod cannot be spread, a
Job's Pod is not a replica of anything, and a DaemonSet already places one Pod per node.
Requiring the field on those produces findings that are correct about the field and wrong
about the cluster, and a report full of those stops being read.

Which workloads must declare a constraint is opted into with a label, so the judgement
stays with whoever knows the replica count:

```yaml
metadata:
  labels:
    resilience.example.com/spread: required
```

### Two ways a declared constraint does nothing

| Written | Why it has no effect |
|---|---|
| No `labelSelector` | The field is optional. Without it the constraint counts no pods, the skew is computed over an empty set, and every placement satisfies it. |
| `labelSelector: {}` | Matches every pod in the namespace, so the workload is spread against its neighbours rather than against its own replicas. |
| `whenUnsatisfiable: ScheduleAnyway` | A preference. The scheduler prefers a placement that reduces skew and then schedules the Pod anyway when it cannot find one. |

The first of those is the true silent no-op: the field is present, anything that greps for
`topologySpreadConstraints` is satisfied, and no scheduling decision is ever affected.

### The rule to argue with

`require-enforced-spread` requires `DoNotSchedule`, and that has a real cost: on a cluster
with fewer topology domains than the constraint needs, Pods stay Pending.

The position taken is that **Pending is a failure you can see** — it appears in `kubectl
get pods`, it trips whatever already alerts on unschedulable Pods, and the scheduler event
names its own cause. `ScheduleAnyway` converts that into an invisible failure: the Pod
runs, the workload reports healthy, and the discovery happens during the node failure the
constraint was written to survive.

If your nodes carry fewer distinct values of the topology key than a workload has
replicas, `ScheduleAnyway` is correct for that cluster and this rule is the wrong rule for
it — drop the rule rather than work around it. Check before deciding:

```sh
kubectl get nodes -L topology.kubernetes.io/zone
```

### What is deliberately not checked

`maxSkew`, `topologyKey` and `whenUnsatisfiable` are all required fields, and `maxSkew`
must be greater than zero. A rule requiring them would re-state a check the API server
already performs, and would reject a Pod that cannot be submitted in the first place — a
rule that can never fire, which in a policy report looks exactly like a rule that is
working.

Nor can these rules tell whether `topologyKey` names a label the nodes actually carry. A
constraint keyed on a label no node has puts every node in one unnamed domain, where any
distribution is perfectly balanced. That is a cluster fact rather than a manifest fact,
and the command above is how to check it.
