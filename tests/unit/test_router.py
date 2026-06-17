from __future__ import annotations

from dip.core.config import LLMSettings, RoleModel
from dip.llm.client import LLMResponse, Message
from dip.llm.router import LLMRouter


class FakeClient:
    def generate(self, messages, *, temperature=None, max_tokens=None) -> LLMResponse:
        return LLMResponse(text="", model="fake", raw={})


def test_role_overrides_applied() -> None:
    base = LLMSettings(
        model="base-model",
        temperature=0.1,
        roles={
            "planner": RoleModel(model="planner-model", temperature=0.3),
            "coder": RoleModel(temperature=0.0),  # model unset -> base model
        },
    )
    assert base.for_role("planner").model == "planner-model"
    assert base.for_role("planner").temperature == 0.3
    # coder keeps the base model but overrides temperature.
    assert base.for_role("coder").model == "base-model"
    assert base.for_role("coder").temperature == 0.0


def test_unconfigured_role_falls_back_to_base() -> None:
    base = LLMSettings(model="base-model", temperature=0.2)
    assert base.for_role("reviewer").model == "base-model"
    assert base.for_role("reviewer").temperature == 0.2


def test_router_resolved_model() -> None:
    base = LLMSettings(model="base", roles={"reviewer": RoleModel(model="rev", temperature=0.4)})
    router = LLMRouter(base)
    assert router.resolved_model("reviewer") == ("rev", 0.4)
    assert router.resolved_model("coder")[0] == "base"


def test_override_returned_for_every_role() -> None:
    fake = FakeClient()
    router = LLMRouter(LLMSettings(), override=fake)
    assert router.for_role("planner") is fake
    assert router.for_role("coder") is fake
    assert router.for_role("anything") is fake


def test_clients_cached_per_role() -> None:
    router = LLMRouter(LLMSettings())
    first = router.for_role("planner")
    assert router.for_role("planner") is first  # cached, not rebuilt
