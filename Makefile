# Local entry points for this policy library.
#
# Every validation flag below is identical to the one in .github/workflows/ci.yml.
# A local run that is quieter than the pipeline is worse than no local run, because
# it is trusted. `make ci` chains the four checks in pipeline order.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# Pinned to match the pipeline. Two of this library's constructs are version-dependent
# — the per-rule failureAction fields and the generate-level generateExisting — so a
# floating version would move the definition of a passing run.
KYVERNO_VERSION ?= v1.19.1

KYVERNO ?= kyverno
PYTHON  ?= python3
DIST    ?= dist

# The policies applied by `apply`, `admissible` and `report`, listed once so the three
# cannot drift apart. The signing policy is named out rather than the images directory
# being passed, because a verifyImages rule reaches a verdict by contacting a registry
# and there is none here; the supply-chain set is left out for the same reason.
VALIDATING_POLICIES := \
	policies/images/restrict-image-registries.yaml \
	policies/images/disallow-mutable-image-tags.yaml \
	policies/pod-security/ \
	policies/resources/ \
	policies/network/

# Every fixture the pipeline builds its report over.
REPORT_RESOURCES := \
	--resource tests/images/resource.yaml \
	--resource tests/images-autogen/resource.yaml \
	--resource tests/pod-security/resource.yaml \
	--resource tests/resources/resource.yaml \
	--resource tests/network/resource.yaml \
	--resource tests/compliant/resource.yaml

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

.PHONY: require-kyverno
require-kyverno:
	@command -v $(KYVERNO) >/dev/null 2>&1 || { \
		echo "kyverno CLI not found. Install $(KYVERNO_VERSION) with 'make install-cli',"; \
		echo "or see https://kyverno.io/docs/kyverno-cli/"; exit 1; }

.PHONY: install-cli
install-cli: ## Print how to install the pinned Kyverno CLI
	@echo "The pipeline installs $(KYVERNO_VERSION) via kyverno/action-install-cli."
	@echo "Locally, install the same version from:"
	@echo "  https://github.com/kyverno/kyverno/releases/tag/$(KYVERNO_VERSION)"
	@echo "then confirm with 'make version'."

.PHONY: version
version: require-kyverno ## Show which CLI version is actually on PATH
	@$(KYVERNO) version

.PHONY: lint
lint: ## Lint the policies, the tests and the workflow
	yamllint -c .yamllint policies/ tests/ .github/workflows/
	flake8 --select=E9,F63,F7,F82 --show-source tests/
	flake8 --max-line-length=100 tests/
	git ls-files '*.py' | xargs -r -n1 python -m py_compile

.PHONY: gate
gate: ## Check that the test suite still covers what it claims to
	$(PYTHON) tests/lint_test_manifests.py

.PHONY: test
test: require-kyverno ## Run the Kyverno CLI test cases
	$(KYVERNO) test tests/ --require-tests --detailed-results

.PHONY: admissible
admissible: require-kyverno ## Assert one workload satisfies every validating rule at once
	$(KYVERNO) apply $(VALIDATING_POLICIES) --resource tests/compliant/resource.yaml

.PHONY: apply
apply: ## Check a manifest against the validating policies: make apply RESOURCE=path
	@# The argument is checked before the tool deliberately. As a prerequisite,
	@# require-kyverno would run first and report a missing binary for what is
	@# actually a missing argument — the one error message the caller can act on.
	@test -n "$(RESOURCE)" || { echo "usage: make apply RESOURCE=my-workload.yaml"; exit 1; }
	@test -f "$(RESOURCE)" || { echo "no such file: $(RESOURCE)"; exit 1; }
	@$(MAKE) --no-print-directory require-kyverno
	$(KYVERNO) apply $(VALIDATING_POLICIES) --resource "$(RESOURCE)"

.PHONY: report
report: require-kyverno ## Build a policy report over every fixture
	@mkdir -p $(DIST)
	$(KYVERNO) apply $(VALIDATING_POLICIES) $(REPORT_RESOURCES) \
		--policy-report \
		--output-format yaml \
		--audit-warn \
		--warn-exit-code 0 \
		| tee $(DIST)/policy-report.yaml
	@echo "written to $(DIST)/policy-report.yaml"

.PHONY: ci
ci: lint gate test admissible ## Everything the pipeline gates on, in pipeline order

.PHONY: clean
clean: ## Remove generated output
	rm -rf $(DIST) kyverno-test-results/
	find . -name '__pycache__' -type d -prune -exec rm -rf {} +
