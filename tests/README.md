# Tests

Two layers, and they check different things.

`kyverno test tests/` runs every `kyverno-test.yaml` below through the same engine that
will evaluate these policies in a cluster. It is the only thing here that knows what
Kyverno actually does — whether a conditional anchor skips an absent list, whether a
registry with no hostname normalises to `docker.io`, whether auto-generation really
covers a Deployment.

`tests/lint_test_manifests.py` checks the suite itself. It exists because `kyverno test`
verifies the expectations that are written down and says nothing about the ones that are
not: a rule with no entry in any manifest is untested, the command still exits zero, and
a green pipeline reports the same thing either way.

## Layout

| Directory | Policies under test |
|---|---|
| `images/` | `restrict-image-registries`, `disallow-mutable-image-tags` |
| `images-autogen/` | `disallow-mutable-image-tags` against Deployments |
| `pod-security/` | `require-pod-security-standards`, `require-read-only-root-filesystem` |
| `resources/` | `require-resource-requests-and-limits`, `require-safe-disruption-budgets`, `require-topology-spread-constraints` |
| `network/` | `require-network-identity-labels` |
| `generate/` | `add-default-network-policies` |

`resources/` mirrors the policy set of the same name. It holds the tests for
`policies/resources/`, not the resource fixtures — every directory here has its fixtures
in its own `resource.yaml`.

## Conventions

**Every rule is expected to pass somewhere and fail somewhere.** A rule that is only ever
expected to pass would produce exactly the same result if it matched nothing at all, and
that is the failure this whole library is written around. The coverage gate enforces both
directions; the one exception is a generate rule, which creates its resource or does not
and has no failing verdict to assert.

**Each fixture is one deviation from a compliant one.** When a fixture is meant to fail a
single rule it satisfies every other rule in the manifest, so a failure names the rule
that caused it rather than a fixture that was wrong in several ways at once.

**A fixture never describes a Pod the API would reject.** `privileged-container` leaves
`allowPrivilegeEscalation` unset rather than setting it false, because the API refuses
that combination and a fixture the API server would not admit tests nothing.

**Every fixture is named by an expectation.** An unreferenced fixture is one somebody
believes is covered.

## What is deliberately not tested here, and why

**Image verification and attestations.** `require-image-signatures` and the three
`supply-chain` policies are `verifyImages` rules. Reaching a verdict means contacting a
registry and checking a signature or a predicate, so a meaningful test needs a signed
image published where the test can read it — not a YAML fixture. The CLI can do this with
`--registry` against real credentials; until this library publishes a signed test image,
these rules are exercised by review and by the structural checks, and that gap is real
rather than covered.

The attestation policies carry the `cosign download attestation` command that answers the
predicate-type question from a real image, which is more useful than a fixture asserting
the answer this library guessed.

**Namespace exclusions.** Every rule excludes `kube-system` and three others. A resource
in an excluded namespace is not matched at all, so there is no verdict to expect, and an
expectation naming it would be asserting something about the absence of a result rather
than about the rule. Who can create a Pod in those namespaces is the control that matters
there.

**The generate set's negative direction.** `add-default-network-policies` matches only a
Namespace carrying the opt-in label, and that label is the whole of the set's safety. The
positive direction is asserted; the negative one is a match that never happens, which is
the same absence-of-a-result case as above.

**Whether the registry rule resolves the same way under auto-generation.** The
`images-autogen` case loads the tag policy alone. The registry rule reads a context
variable built from the Pod's image list, and whether that resolves identically for a rule
Kyverno generated is a separate question from whether generation happens at all.

## Running them

```sh
kyverno test tests/ --require-tests
python3 tests/lint_test_manifests.py
```

`--require-tests` matters: without it, a run that finds no tests at all exits zero. That
is the same shape as a rule that matches nothing, one level further out.

`--warnings-as-errors` is deliberately **not** used. This library targets `ClusterPolicy`,
which current Kyverno marks deprecated in favour of the CEL policy types, for reasons
recorded in the root README. Treating that warning as an error would turn a documented
decision into a broken pipeline.
