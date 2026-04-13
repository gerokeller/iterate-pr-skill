# Providers

Each `*.py` file in this directory contributes provider-specific detection and recovery guidance for PR checks and review comments. A provider is anything that produces a GitHub check, status context, or bot comment on a PR — CI platforms, preview-environment services (Supabase, Vercel), coverage reporters (Codecov), code-quality tools (Codacy), AI review bots (CodeRabbit), error-monitoring bots (Sentry), etc.

The registry in `__init__.py` auto-discovers every non-underscored `*.py` in this directory at import time, expecting each to export a module-level `PROVIDER` instance of `Provider` (see `_base.py`).

## Adding a provider

Create `<name>.py`:

```python
from __future__ import annotations
import re
from ._base import Provider, RecoveryHint

def _recovery(family, status, markers):
    if family != "myprovider-deploy" or status not in {"fail", "cancel", "pending"}:
        return None
    return RecoveryHint(
        classification="myprovider-deploy",
        summary="Deploy failed; check the details URL.",
        recommended_steps=(
            "Open the details URL and capture the concrete failure.",
            "If it's a transient infra blip, rerun once.",
        ),
        stop_only_after="Inspecting the failure and attempting one rerun",
    )

PROVIDER = Provider(
    name="myprovider",
    detect_keywords=("myprovider",),
    family_rules=((("myprovider", "deploy"), "myprovider-deploy"),),
    failure_marker_patterns=(
        ("BUILD_FAILED", re.compile(r"\bBUILD FAILED\b")),
    ),
    bot_author_patterns=(re.compile(r"(?i)^myprovider-bot"),),
    recovery_builder=_recovery,
)
```

### Field reference

| Field | Purpose |
|-------|---------|
| `name` | Stable provider identifier used in script output (`"provider": "<name>"`). |
| `detect_keywords` | Case-insensitive substrings. If any appears in `"<check-name> <workflow> <link>"`, the check is tagged with this provider. |
| `family_rules` | Ordered list of `((kw1, kw2, ...), family-name)`. First entry whose keywords all match wins. Fed to `check_family` in script output. |
| `failure_marker_patterns` | `(MARKER_NAME, compiled-regex)`. Scanned against log snippets; any matches populate `failure_markers` on the check. |
| `bot_author_patterns` | Regexes matched against comment authors. Matches classify the comment as `bot` feedback. |
| `recovery_builder` | `(family, status, markers) -> RecoveryHint \| None`. Emits `recovery_hint` on failing checks. |

## Agent-facing docs

Optionally add `<name>.md` with recovery ladder, stop-reason vocabulary, evidence format, and links. The skill's `SKILL.md` instructs the agent to read `providers/<name>.md` on-demand when a failing check carries `provider: "<name>"`. This keeps provider-specific prose out of `SKILL.md` unless the provider is actually present in the repo being worked on.

## Registry API

Consumed by `scripts/fetch_pr_checks.py` and `scripts/fetch_pr_feedback.py`:

| Function | Returns |
|----------|---------|
| `PROVIDERS` | List of loaded providers. |
| `detect_provider(name, workflow, link, fallback=None)` | Provider name of the first match, else fallback. |
| `classify_family(provider, name, workflow, link)` | Sub-family string for a given provider, else None. |
| `all_failure_markers()` | Aggregated `(marker, pattern)` tuples for log scanning. |
| `bot_author_patterns()` | Aggregated generic + provider-contributed bot regexes. |
| `build_recovery_hint(provider, family, status, markers)` | Provider-specific hint dict, else None. |
