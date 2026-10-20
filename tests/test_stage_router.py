"""Etapas: 02-lab antes de 03-plan, texto simple y reutilización en O2."""

from dataclasses import replace
from datetime import datetime, timezone

from universal_bot.code_mode.fake_discord import FakeDiscord
from universal_bot.code_mode.models import Project, ProjectMode, ProjectState
from universal_bot.code_mode.stage_router import (
    StageOrderError,
    StageRouter,
    render_plain,
    render_technical,
)

T0 = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def project(**overrides) -> Project:
    base = Project(
        id="P-1",
        guild_id=1,
        requester_id=7,
        origin_message_id=1,
        slug="reservas-api",
        title_plain="Reservas",
        tier="T2",
        work_type="evolving-product",
        mode=ProjectMode.CHANNEL,
        state=ProjectState.LAB_RUNNING,
        channel_id=10,
        root_thread_id=None,
        run_id="R-1",
        wave="O1",
        sandbox_id="sb",
        last_security_check=None,
        requires_production=False,
        created_at=T0,
        updated_at=T0,
    )
    return replace(base, **overrides)


def test_lab_is_required_before_plan():
    router = StageRouter(FakeDiscord())
    item = project()
    try:
        router.enter(item, "03-plan")
        raised = False
    except StageOrderError:
        raised = True
    assert raised is True
    lab = router.enter(item, "02-lab")
    plan = router.enter(item, "03-plan")
    assert lab.key == "02-lab"
    assert plan.key == "03-plan"
    assert [thread.name for thread in router.discord.threads] == ["02-lab", "03-plan"]


def test_channel_posts_jargon_only_in_the_stage_thread_and_nothing_in_the_channel():
    """Modo canal con hilo conocido: el detalle va al hilo y el canal no recibe un resumen duplicado por etapa."""
    discord = FakeDiscord()
    router = StageRouter(discord)
    router.post(project(), "02-lab", "Miré el diff y corrí pytest")
    router.post(project(), "03-plan", "Plan: dos pasos")
    lab, plan = discord.threads
    assert (lab.name, plan.name) == ("02-lab", "03-plan")
    assert [(m.thread_id, m.content) for m in discord.messages] == [
        (lab.id, "Miré el diff y corrí pytest"),
        (plan.id, "Plan: dos pasos"),
    ]
    assert [m for m in discord.messages if m.thread_id is None] == []


def test_thread_mode_prefixes_the_stage_and_skips_stage_threads():
    discord = FakeDiscord()
    router = StageRouter(discord)
    item = project(mode=ProjectMode.THREAD, channel_id=700, root_thread_id=9)
    router.post(item, "02-lab", "vi el diff")
    assert discord.threads == []
    assert discord.messages[0].content == "[02-lab] vi el diff"
    assert discord.messages[0].thread_id == 9
    assert discord.messages[1].content == "vi el"
    assert discord.messages[1].thread_id == 9


def test_o2_reuses_impl_and_verification_threads():
    discord = FakeDiscord()
    router = StageRouter(discord)
    item = project()
    for stage_key in ("04-impl-api", "05-verificacion"):
        router.post(item, stage_key, "primer pase")
    assert [thread.name for thread in discord.threads] == ["04-impl-api", "05-verificacion"]
    first_ids = {thread.name: thread.id for thread in discord.threads}
    follow = replace(item, wave="O2")
    for stage_key in ("04-impl-api", "05-verificacion"):
        router.post(follow, stage_key, "segundo pase")
    assert [thread.name for thread in discord.threads] == ["04-impl-api", "05-verificacion"]
    headers = [message.content for message in discord.messages if message.content.startswith("O2 · correctiva")]
    assert headers == [
        "O2 · correctiva\nsegundo pase",
        "O2 · correctiva\nsegundo pase",
    ]
    reused = [message.thread_id for message in discord.messages if message.content.startswith("O2")]
    assert reused == [first_ids["04-impl-api"], first_ids["05-verificacion"]]


def test_plain_render_drops_blacklisted_words_and_technical_keeps_them():
    assert render_plain("Miré el diff del PR y corrí pytest") == "Miré el del y corrí"
    assert render_plain("diff PR stack commit merge pytest") == ""
    assert render_plain("El commit del merge") == "El del"
    assert render_plain("corrí pytest, después") == "corrí después"
    assert render_technical("corrí pytest") == "corrí pytest"
