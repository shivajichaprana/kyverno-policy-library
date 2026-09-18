#!/usr/bin/env python3
"""Check the test suite itself, which `kyverno test` cannot.

`kyverno test` verifies the expectations that are written down. It says nothing
about the expectations that are not. A rule with no entry in any manifest is
silently untested and the command still exits zero, so a library can grow a
policy set that nothing exercises and the pipeline stays green — the same shape
as the failure the policies themselves are written around, one level up.

What this gate adds:

  Coverage        Every rule of every tested policy has at least one PASS and at
                  least one FAIL expectation. A rule expected only to pass would
                  report exactly the same result if it matched nothing at all,
                  so the passing direction on its own proves nothing.

  Completeness    Every policy file on disk is either covered by a manifest or
                  named in UNTESTED with a reason, checked in both directions:
                  a new policy set with no tests fails here, and so does a
                  policy removed from UNTESTED without gaining tests.

  Integrity       Every path, policy name, rule name and resource name in a
                  manifest resolves, and every declared kind matches the kind of
                  the resource it names. A typo in any of them makes an
                  expectation match nothing, and an expectation that matches
                  nothing is not reported as a failure by the test command.

  Fixtures        Every resource in a test's resource files is named by at least
                  one expectation. An unreferenced fixture is one somebody
                  believes is covered.

  Regression      The three deprecated or refused constructs this library has
                  already been through once cannot come back silently.

Exit status is 1 on any rejection. Reads the working tree, so what is checked is
what would be committed.
"""

from __future__ import annotations

import pathlib
import sys

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
POLICY_GLOB = "policies/*/*.yaml"
RESULT_VALUES = {"pass", "fail", "skip", "warn"}

# A policy is tested, or it is here with the reason it is not. Both directions are
# checked, so this list cannot drift away from the tree in either direction.
UNTESTED = {
    "policies/images/require-image-signatures.yaml":
        "verifyImages: reaching a verdict means contacting a registry and checking "
        "a signature, so a meaningful test needs a signed image published where the "
        "test can read it.",
    "policies/supply-chain/require-build-provenance.yaml":
        "verifyImages with attestations: needs a signed provenance statement "
        "attached to a real image.",
    "policies/supply-chain/require-sbom-attestation.yaml":
        "verifyImages with attestations: needs a signed CycloneDX document "
        "attached to a real image.",
    "policies/supply-chain/require-recent-vulnerability-scan.yaml":
        "verifyImages with attestations: needs a signed scan attestation, and its "
        "conditions are time-relative so a fixture would expire.",
    "policies/generate/background-controller-rbac.yaml":
        "not a policy — the ClusterRole the generate set cannot function without.",
}

# A generate rule creates its resource or it does not; there is no failing verdict
# to assert, so the both-directions rule does not apply to one.
KINDS_WITHOUT_FAIL_DIRECTION = "generate"

failures: list[str] = []
checks = 0


def check(ok: bool, message: str) -> None:
    global checks
    checks += 1
    if not ok:
        failures.append(message)


def load_all(path: pathlib.Path) -> list[dict]:
    with path.open() as handle:
        return [doc for doc in yaml.safe_load_all(handle) if doc]


def policy_rules(doc: dict) -> dict[str, str]:
    """Rule name -> rule type, for one policy document."""
    types = {}
    for rule in (doc.get("spec") or {}).get("rules") or []:
        name = rule.get("name")
        if not name:
            continue
        for kind in ("validate", "verifyImages", "generate", "mutate"):
            if kind in rule:
                types[name] = kind
                break
        else:
            types[name] = "unknown"
    return types


def main() -> int:
    policy_files = sorted(REPO.glob(POLICY_GLOB))
    check(bool(policy_files), "no policy files found — is this the right tree?")

    # ---------------------------------------------------------------- policies
    policies: dict[str, tuple[str, dict[str, str]]] = {}
    for path in policy_files:
        rel = path.relative_to(REPO).as_posix()
        for doc in load_all(path):
            kind = doc.get("kind")
            if kind not in ("ClusterPolicy", "Policy"):
                continue
            name = (doc.get("metadata") or {}).get("name")
            check(bool(name), f"{rel}: policy with no metadata.name")
            policies[name] = (rel, policy_rules(doc))
            spec = doc.get("spec") or {}

            # Regression guards for constructs this library has been through once.
            check("validationFailureAction" not in spec,
                  f"{rel}: policy-level validationFailureAction is deprecated — set "
                  f"failureAction on the rule")
            check("generateExisting" not in spec,
                  f"{rel}: policy-level generateExisting is deprecated — set it "
                  f"inside the generate block")
            for rule in spec.get("rules") or []:
                for idx, verify in enumerate(rule.get("verifyImages") or []):
                    at = f"{rel}/{rule.get('name')}/verifyImages[{idx}]"
                    check(verify.get("mutateDigest") is not True,
                          f"{at}: Kyverno refuses mutateDigest: true while the "
                          f"failure action is Audit, and Audit is the default")

    # ------------------------------------------------------------- manifests
    manifests = sorted(REPO.glob("tests/*/kyverno-test.yaml"))
    check(bool(manifests), "no kyverno-test.yaml files found under tests/")

    covered_files: set[str] = set()
    directions: dict[tuple[str, str], set[str]] = {}
    seen: set[tuple[str, str, str, str]] = set()

    for manifest in manifests:
        rel = manifest.relative_to(REPO).as_posix()
        docs = load_all(manifest)
        check(len(docs) == 1, f"{rel}: expected one Test document, found {len(docs)}")
        if len(docs) != 1:
            continue
        test = docs[0]
        check(test.get("apiVersion") == "cli.kyverno.io/v1alpha1",
              f"{rel}: apiVersion is {test.get('apiVersion')!r}")
        check(test.get("kind") == "Test", f"{rel}: kind is {test.get('kind')!r}")
        check(bool((test.get("metadata") or {}).get("name")),
              f"{rel}: no metadata.name")

        # Policies referenced by this manifest.
        local: dict[str, dict[str, str]] = {}
        check(bool(test.get("policies")), f"{rel}: no policies listed")
        for ref in test.get("policies") or []:
            target = (manifest.parent / ref).resolve()
            if not target.exists():
                check(False, f"{rel}: policy path does not resolve: {ref}")
                continue
            covered_files.add(target.relative_to(REPO).as_posix())
            for doc in load_all(target):
                if doc.get("kind") in ("ClusterPolicy", "Policy"):
                    local[(doc.get("metadata") or {})["name"]] = policy_rules(doc)

        # Resources available to this manifest.
        fixtures: dict[str, str] = {}
        check(bool(test.get("resources")), f"{rel}: no resources listed")
        for ref in test.get("resources") or []:
            target = (manifest.parent / ref).resolve()
            if not target.exists():
                check(False, f"{rel}: resource path does not resolve: {ref}")
                continue
            for doc in load_all(target):
                name = (doc.get("metadata") or {}).get("name")
                check(bool(name), f"{rel}: fixture with no metadata.name in {ref}")
                if name:
                    check(name not in fixtures,
                          f"{rel}: two fixtures named {name!r} in {ref}")
                    fixtures[name] = doc.get("kind")

        referenced: set[str] = set()
        results = test.get("results") or []
        check(bool(results), f"{rel}: no results declared")
        for index, result in enumerate(results):
            at = f"{rel}/results[{index}]"
            policy = result.get("policy")
            rule = result.get("rule")
            outcome = result.get("result")
            kind = result.get("kind")
            names = result.get("resources") or []

            check(policy in local,
                  f"{at}: policy {policy!r} is not one of the policies this "
                  f"manifest loads")
            check(outcome in RESULT_VALUES, f"{at}: result {outcome!r} is not one of "
                                            f"{sorted(RESULT_VALUES)}")
            check(bool(kind), f"{at}: no kind declared")
            check(bool(names), f"{at}: no resources declared")

            rules = local.get(policy) or {}
            check(rule in rules,
                  f"{at}: policy {policy!r} declares no rule {rule!r}")
            if policy in local and rule in rules and outcome in RESULT_VALUES:
                directions.setdefault((policy, rule), set()).add(outcome)

            generated = result.get("generatedResource")
            if generated is not None:
                target = manifest.parent / generated
                check(target.exists(),
                      f"{at}: generatedResource does not resolve: {generated}")

            for name in names:
                referenced.add(name)
                check(name in fixtures,
                      f"{at}: no fixture named {name!r} in this manifest's resources")
                if name in fixtures:
                    check(fixtures[name] == kind,
                          f"{at}: {name!r} is a {fixtures[name]}, not a {kind}")
                key = (policy, str(rule), str(kind), name)
                check(key not in seen,
                      f"{at}: {name!r} already has an expectation for "
                      f"{policy}/{rule}")
                seen.add(key)

        for name in sorted(set(fixtures) - referenced):
            check(False, f"{rel}: fixture {name!r} is named by no expectation — an "
                         f"unreferenced fixture is one somebody believes is covered")

    # -------------------------------------------------------------- coverage
    for name, (rel, rules) in sorted(policies.items()):
        if rel in UNTESTED:
            continue
        for rule, rule_type in sorted(rules.items()):
            got = directions.get((name, rule))
            check(bool(got), f"{rel}: rule {rule!r} has no expectation in any "
                             f"manifest — it is untested and the test command "
                             f"reports nothing about it")
            if not got:
                continue
            check("pass" in got,
                  f"{rel}: rule {rule!r} has no passing expectation")
            if rule_type != KINDS_WITHOUT_FAIL_DIRECTION:
                check("fail" in got,
                      f"{rel}: rule {rule!r} has no failing expectation — the "
                      f"passing direction alone would look identical if the rule "
                      f"matched nothing")

    # ----------------------------------------------------------- completeness
    on_disk = {p.relative_to(REPO).as_posix() for p in policy_files}
    for rel in sorted(on_disk):
        check(rel in covered_files or rel in UNTESTED,
              f"{rel}: no test manifest loads this file and it is not named in "
              f"UNTESTED with a reason")
    for rel in sorted(UNTESTED):
        check(rel in on_disk,
              f"UNTESTED names {rel}, which is not in the tree")
        check(rel not in covered_files,
              f"{rel} is named in UNTESTED but a manifest loads it — remove the "
              f"entry rather than keeping both")

    for message in failures:
        print(f"FAIL: {message}")
    print(f"{checks - len(failures)}/{checks} test-suite checks passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
