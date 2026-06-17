"""Rule-of-three abstraction gate (count-based).

The reviewer/agent supplies an abstraction's concrete use count; the rule is
the threshold. Full AST call-site discovery is deferred (live-run); this is
the checkable core: no abstraction earns its keep before the third use."""


def check(name: str, use_count: int) -> tuple[bool, str]:
    if use_count < 3:
        return (False, f"{name}: {use_count} use(s) — wait for the third use "
                       f"before abstracting (two call sites get duplication)")
    return (True, f"{name}: {use_count} uses — abstraction earned")
