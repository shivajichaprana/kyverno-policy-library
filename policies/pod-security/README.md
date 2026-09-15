# Pod security policies

Two policies covering what a Pod must look like to be allowed to run: the Kubernetes Pod
Security Standards, and the one hardening control the standards leave out.

| Policy | Rules | What it catches |
|---|---|---|
| `require-pod-security-standards.yaml` | `validate-baseline-profile`, `validate-restricted-profile` | A Pod that is dangerous (baseline) or merely unhardened (restricted) |
| `require-read-only-root-filesystem.yaml` | `validate-read-only-root-filesystem` | A container that can write to its own image layer |

## Before applying these

Nothing. Unlike the image policies, these carry no placeholders — there is no registry
hostname, no organisation name and no key to substitute, because the standards are the
same everywhere. Applied unchanged they produce a true report of what the cluster is
running.

```sh
kubectl apply -f policies/pod-security/
kubectl get policyreport -A
```

The first report on an existing cluster is usually long. That is the point of it.

## What the profiles cover

`restricted` is inclusive of `baseline`, so the second rule is a superset of the first.

| Profile | Controls |
|---|---|
| `baseline` | Host namespaces, privileged containers, capabilities beyond the default set, hostPath volumes, host ports, AppArmor, SELinux, `/proc` mount type, seccomp (unconfined forbidden), sysctls, HostProcess containers |
| `restricted` | Everything above, plus volume types, privilege escalation, running as non-root, running as a non-root UID, seccomp set to `RuntimeDefault` or `Localhost`, and capabilities dropped to `ALL` |

## Why these are a `podSecurity` subrule and not hand-written patterns

`runAsNonRoot`, `seccompProfile` and the capability set can each be specified on the Pod,
on the container, or on both — and where both exist, the container wins. That single fact
makes the obvious hand-written rule wrong in one of two directions, and wrong quietly:

| The rule you would write | What it does to a compliant Pod | What it does to a hole |
|---|---|---|
| Pattern over `spec.containers[].securityContext.runAsNonRoot` | **Fails** a Pod that set the field once at `spec.securityContext` and inherits it. A report full of false violations is a report nobody reads. | Catches it |
| Pattern over `spec.securityContext.runAsNonRoot` | Passes it | **Misses** a Pod that sets `true` at the top and `false` on one container — which is what an exemption-by-stealth looks like |

The `podSecurity` subrule links the same library Kubernetes' own Pod Security Admission
uses, so the resolution is the real one. Its failure text says as much: `pod or container
"x" must set securityContext.runAsNonRoot=true`.

The read-only root filesystem policy is a `pattern` for the mirror-image reason — that
field has no Pod-level form at all, so there is nothing to resolve. Rule type follows
where the field lives.

## Why not just label the namespaces

Pod Security Admission is driven by a label on each namespace, and a namespace created
without one is governed by nothing. Nothing reports that absence, because an ungoverned
namespace and a compliant namespace produce the same empty finding list. These rules
match every Pod in the cluster except four named namespaces, so coverage is the default
and the exclusion is the part written down.

Kyverno's implementation also allows exempting individual controls, reports through
`PolicyReport` rather than only rejecting at the API, and can be run against manifests in
a pipeline before anything reaches a cluster. The built-in admission controller does none
of those.

## Adopting these

The two profiles are separate rules so that the usual adoption path is a single field
edit rather than a rewrite:

1. Apply both in `Audit` and read the reports.
2. Fix, or grant a `PolicyException` to, everything the **baseline** rule reports.
3. Move `validate-baseline-profile` to `failureAction: Enforce`. Dangerous Pods are now
   refused; unhardened ones are still only reported.
4. Work through the **restricted** report, which is the longer of the two.
5. Move `validate-restricted-profile` to `Enforce`.

`failureActionOverrides` raises a single namespace ahead of the rest, which is the usual
way to prove a rule in one place first.

Pin `version` before moving anything to `Enforce`. `latest` means the standards track the
running Kyverno build, so a Kyverno upgrade can change what is enforced with nothing in
this repository's history to explain it. Turning enforcement on and changing what is
enforced should not be the same event.

## Excluding a control, and the half-exclusion trap

`podSecurity.exclude[]` exempts named controls while keeping the rest of the profile.
Where a control's restricted fields live decides how many entries it needs:

| The control's fields live at | Entry needed |
|---|---|
| Pod `spec` only | `controlName` |
| `containers[]` only | `controlName` plus `images[]` |
| **Both** | **Two entries** — one of each |

Supplying one entry for a both-levels control excludes half of it. The half still in
force keeps rejecting things, and the exclusion looks like it was applied, so the
investigation starts in the wrong place. Seccomp is the common case, because its field is
settable on the Pod and on each container:

```yaml
exclude:
  - controlName: Seccomp          # the spec-level half
  - controlName: Seccomp          # the containers[] half
    images:
      - '*'
```

Scope container-level exemptions to the image that needs them — a service mesh sidecar is
the usual honest reason — rather than to `'*'`:

```yaml
exclude:
  - controlName: Capabilities
    images:
      - '*/proxy-init:*'
```

Neither policy in this directory ships with any control excluded. An exclusion is a hole,
and a hole that arrives with the library is one nobody chose.

## Known consequences

Both of these are deliberate, and both will show up in the first report:

- **A baseline violation is reported twice.** `restricted` includes `baseline`, so a Pod
  with `hostIPC: true` fails both rules. The duplication is the price of being able to
  adopt the two profiles separately, and it disappears once baseline is clean.
- **`kubectl debug` produces a finding.** The read-only root filesystem rule covers
  `ephemeralContainers`, and debug images generally expect to write. Dropping that list
  would silence it, but an ephemeral container runs inside the target Pod with the target
  Pod's service account — it is exactly what a rule like this should be able to see. Grant
  a `PolicyException` scoped to the debug image instead; an exception is reviewable and an
  omitted list is not.

## What is still not covered

`restricted` plus a read-only root filesystem is a hardened Pod, not a contained one. Out
of scope for this directory and handled elsewhere in the library, or not at all:

| Gap | Where it is handled |
|---|---|
| What the Pod may consume, and how it is spread | `policies/resources/` |
| What the Pod may talk to | `policies/network/` |
| Whether the image is one you published | `policies/images/` |
| Whether the API token is mounted into the Pod | Not covered. `automountServiceAccountToken` defaults to on, and the Pod spec does not show the ServiceAccount's setting, so the honest check needs more than the Pod. |
