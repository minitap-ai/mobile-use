"""P2 robustness fixes (version B). Deterministic, task-agnostic helpers; every caller is gated by
an `AblationConfig.p2_*` flag, so version-A configs never reach this package."""


def p2_flags(ablation) -> dict[str, bool]:
    """Template variables for every `p2_*` flag (all False for version-A configs)."""
    fields = type(ablation).model_fields
    return {name: bool(getattr(ablation, name)) for name in fields if name.startswith("p2_")}
