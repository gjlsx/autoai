from scripts.one_click import compose_routing_with_codex_agent


def _to_map(raw: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item or "=" not in item:
            continue
        k, v = item.split("=", 1)
        out[k.strip()] = int(v.strip())
    return out


def test_compose_routing_injects_codex_agent_targets():
    merged = compose_routing_with_codex_agent(
        "claude=9001,gemini=9002,codex=9003",
        enable_codex_agent=True,
        codex_agent_port=9013,
        sdk_targets={"codex_sdk"},
        app_targets={"codex_app"},
    )
    mapping = _to_map(merged)
    assert mapping["claude"] == 9001
    assert mapping["gemini"] == 9002
    assert mapping["codex"] == 9003
    assert mapping["codex_sdk"] == 9013
    assert mapping["codex_app"] == 9013


def test_compose_routing_keeps_existing_target_ports():
    merged = compose_routing_with_codex_agent(
        "claude=9001,codex_sdk=9901,codex_app=9902,codex=9003",
        enable_codex_agent=True,
        codex_agent_port=9013,
        sdk_targets={"codex_sdk"},
        app_targets={"codex_app"},
    )
    mapping = _to_map(merged)
    assert mapping["codex_sdk"] == 9901
    assert mapping["codex_app"] == 9902


def test_compose_routing_no_injection_when_disabled():
    merged = compose_routing_with_codex_agent(
        "claude=9001,gemini=9002,codex=9003",
        enable_codex_agent=False,
        codex_agent_port=9013,
        sdk_targets={"codex_sdk"},
        app_targets={"codex_app"},
    )
    mapping = _to_map(merged)
    assert "codex_sdk" not in mapping
    assert "codex_app" not in mapping
