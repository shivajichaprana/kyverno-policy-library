# Image policies

Three policies covering the three separate questions an image reference raises: who
published it, where it came from, and whether it will still be the same image tomorrow.

| Policy | Rules | What it catches |
|---|---|---|
| `require-image-signatures.yaml` | `verify-internal-images` | An image from the internal registry that no approved key signed |
| `restrict-image-registries.yaml` | `validate-registries`, `restrict-repository-paths` | An image from an unapproved registry, or from an unapproved account within an approved one |
| `disallow-mutable-image-tags.yaml` | `require-image-tag`, `disallow-latest-tag` | An image reference that can point somewhere else tomorrow |

## Before applying these

Every value in these files is a placeholder. Applied unchanged, they will report every
image in the cluster as a violation — which is harmless in `Audit` mode and is not what
anyone wants to read.

| Replace | In | With |
|---|---|---|
| `registry.example.com` | all three policies | The registry you publish to |
| `ghcr.io/<your-org>/*` | `restrict-image-registries.yaml` | Your account on any shared registry you use |
| `REPLACE_WITH_YOUR_COSIGN_PUBLIC_KEY` | `require-image-signatures.yaml` | The public half of the key your build signs with |

The registry list appears in two files and is deliberately not shared between them.
Kyverno does not permit variables in `verifyImages.imageReferences`, so the signing
policy's scope cannot be read from a ConfigMap even though the registry policy's
allow-list could be. Rather than have half the list in a ConfigMap and half in a file,
both are static. Changing approved registries means editing both files, and a test that
fails on exactly that is the reason the two are checked against each other.

## Why the registry rule reads a variable instead of the image field

`spec.containers[].image` is the string the author typed. Kubernetes fills in the parts
that were left out at pull time, and Kyverno exposes the filled-in form separately as
`images.<list>.<name>`, where an absent registry has become `docker.io` and an official
Docker Hub repository has gained its `library/` prefix.

The two forms disagree for the most common references there are:

| Written | `images.*.registry` | A rule testing the raw field for `docker.io/` |
|---|---|---|
| `nginx` | `docker.io` | does not match — admitted |
| `redis:7.2` | `docker.io` | does not match — admitted |
| `bitnami/redis:7.2` | `docker.io` | does not match — admitted |
| `docker.io/library/nginx:1.27` | `docker.io` | matches — blocked |

A deny-list written against the raw field blocks the one form nobody writes and admits
the three everybody does, while producing exactly the same clean report as a rule that
works. `validate-registries` compares against the normalised registry so all four behave
the same way.

`restrict-repository-paths` does read the raw field, because a prefix match with
alternatives is what a `pattern` expresses well. It therefore has that same blind spot,
which is why it is the second rule and not the only one.

## Signature verification, in practice

- **Scope it to what you sign.** `imageReferences` matches the internal registry only.
  Widening it to `"*"` demands a signature from the CNI, the CSI driver and the pause
  container, and the first node to restart has nothing it can schedule.
- **Verification is cached for 60 minutes by default.** Revoking a key does not take
  effect until the entry expires. Until then the revoked image is still admitted and
  nothing reports otherwise.
- **The digest rewrite causes GitOps drift.** `mutateDigest` replaces the verified tag
  with its digest, which is the point — it closes the window between verifying a tag and
  pulling it. It also means the cluster no longer matches the manifest in git, so a
  reconciler needs to be told to ignore the image field on these workloads.
- **`failurePolicy: Fail` blocks on a Kyverno outage.** `Ignore` avoids that and also
  causes failed registry calls to be ignored, which admits unverified images during a
  registry outage. There is no setting that is safe in both directions.

## What these policies do not cover

- **The excluded namespaces.** `kube-system`, `kube-node-lease`, `kube-public` and
  `kyverno` are outside every rule here. Anyone who can create a Pod in them is past all
  of it, so that access is the control, not these files.
- **A tag that is rewritten.** `disallow-mutable-image-tags` rejects `latest` and requires
  that a tag exists. A team that re-pushes `v1.2.3` still defeats it. Only a digest closes
  that, and requiring digests everywhere is a decision about your release process rather
  than a policy setting.
- **Images already on the node.** A Pod with `imagePullPolicy: IfNotPresent` and a cached
  layer never contacts the registry. Admission still evaluates the reference, but nothing
  here proves the bytes on disk match it.
