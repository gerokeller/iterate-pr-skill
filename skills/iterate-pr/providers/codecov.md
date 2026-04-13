# Codecov

Load this doc when a failing check carries `provider: "codecov"` or `check_family: "codecov-coverage"`.

## Treatment

Treat `codecov/patch` and any other failing Codecov contexts as blockers while `ready_for_merge` is false. Do not describe a failing Codecov check as informational, optional, or safe to ignore unless GitHub explicitly reports the PR as merge-ready after the check settles.

## Recovery

Use the Codecov `detailsUrl` and `recovery_hint` to determine whether the failure is caused by:
- **Low patch coverage** — changed lines aren't tested. Identify the uncovered lines and add tests locally.
- **Low project coverage** — the whole-repo threshold dipped. Usually means the diff reduced coverage somewhere; add tests.
- **Upload/config issues** — the Codecov upload step didn't run or failed. Inspect the paired CI workflow for upload errors; check `codecov.yml` if present.

## Stop reason

Use the generic `blocked-by-checks` or `blocked-by-external-check` (depending on whether the check is a GitHub Actions job or an external status context) once repository-side fixes are exhausted.
