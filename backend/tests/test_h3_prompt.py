from app.core.h3.prompt import (
    validate_h3_prompt,
    compose_h3_prompt,
    enforce_dialogue_occurrences_in_sections,
    ensure_audio_bindings_in_sections,
)
from app.core.projects.models import PromptSections
import pytest


def _sections(soundscape="E"):
    return PromptSections(
        subject_definitions="A",
        summary="B",
        retention_analysis="C",
        detailed_description="D",
        overall_soundscape=soundscape,
        non_diegetic_music="F",
    )


def test_ensure_audio_bindings_adds_missing_tag():
    sections = _sections()
    fixed = ensure_audio_bindings_in_sections(sections, [(1, "recitation")])
    text = compose_h3_prompt(fixed)
    assert "<Audio 1>" in text
    # now satisfies the audio contract that previously rejected the prompt
    validate_h3_prompt(text, [], audio_count=1)


def test_ensure_audio_bindings_is_idempotent():
    sections = _sections(soundscape="bound to <Audio 1> already")
    once = ensure_audio_bindings_in_sections(sections, [(1, "recitation")])
    twice = ensure_audio_bindings_in_sections(once, [(1, "recitation")])
    assert once.overall_soundscape == twice.overall_soundscape
    assert compose_h3_prompt(twice).count("<Audio 1>") == 1


def test_ensure_audio_bindings_only_adds_missing_indexes():
    sections = _sections(soundscape="uses <Audio 1> but not the second voice")
    fixed = ensure_audio_bindings_in_sections(
        sections, [(1, "one"), (2, "two")]
    )
    text = compose_h3_prompt(fixed)
    assert "<Audio 1>" in text and "<Audio 2>" in text
    validate_h3_prompt(text, [], audio_count=2)


def test_ensure_audio_bindings_forces_diegetic_lip_sync():
    # A narrator/voice-over framing (tag present, no mouth-sync) must still get a
    # diegetic lip-sync directive so the on-screen character visibly recites.
    sections = _sections(
        soundscape="a young girl's voice recites over the scene in <Audio 1>"
    )
    fixed = ensure_audio_bindings_in_sections(sections, [(1, "recitation")])
    text = compose_h3_prompt(fixed)
    assert "mouth" in text and "sync" in text
    assert "NOT a disembodied narrator" in text
    # the tag is not duplicated by the lip-sync clause
    assert text.count("<Audio 1>") == 1


def test_ensure_audio_bindings_skips_lip_sync_when_already_present():
    sections = _sections(
        soundscape="the cat's mouth moves in sync with <Audio 1>"
    )
    fixed = ensure_audio_bindings_in_sections(sections, [(1, "recitation")])
    assert "disembodied" not in fixed.overall_soundscape


def test_ensure_audio_bindings_forces_mouth_visibility_in_description():
    # A mouth-hiding composition (high-angle into a basket, heads down) with no
    # mouth cue in detailed_description must get a mouth-visibility directive
    # injected into the conditioning payload, not just the soundscape.
    sections = PromptSections(
        subject_definitions="DALI and XIAOBAI at a basket",
        summary="B",
        retention_analysis="C",
        detailed_description=(
            "high angle looking down into a bamboo basket, the cats' heads "
            "lowered peering into the beans"
        ),
        overall_soundscape="a young girl's voice recites in <Audio 1>",
        non_diegetic_music="F",
    )
    fixed = ensure_audio_bindings_in_sections(sections, [(1, "recitation")])
    dd = fixed.detailed_description.lower()
    assert "mouth" in dd and "visible to camera" in dd
    assert "do not use a top-down" in dd
    # idempotent
    again = ensure_audio_bindings_in_sections(fixed, [(1, "recitation")])
    assert again.detailed_description == fixed.detailed_description


def test_order_and_dialogue():
    sections = PromptSections(
        subject_definitions="A",
        summary="B\n<Subject 1> (S1): <d>[Chinese] 几点？</d>",
        retention_analysis="C",
        detailed_description="D",
        overall_soundscape="E",
        non_diegetic_music="F",
    )
    text = compose_h3_prompt(sections)
    validate_h3_prompt(text, ["几点？"])
    with pytest.raises(ValueError, match="section order"):
        validate_h3_prompt(text.replace("summary:", "x:"), ["几点？"])


def test_duplicate_dialogue_lines_repeat_once_per_occurrence():
    sections = PromptSections(
        subject_definitions="A",
        summary="B",
        retention_analysis="C",
        detailed_description="Dali laughs hahaha, then xiaobai laughs hahaha.",
        overall_soundscape="E",
        non_diegetic_music="F",
    )
    text = compose_h3_prompt(sections)

    # Two characters share the same line: it must appear twice.
    validate_h3_prompt(text, ["hahaha", "hahaha"])

    with pytest.raises(ValueError, match="exactly 3 times"):
        validate_h3_prompt(text, ["hahaha", "hahaha", "hahaha"])

    with pytest.raises(ValueError, match="exactly once"):
        validate_h3_prompt(text, ["hahaha"])


def _six(desc="D", soundscape="E"):
    return PromptSections(
        subject_definitions="A",
        summary="B",
        retention_analysis="C",
        detailed_description=desc,
        overall_soundscape=soundscape,
        non_diegetic_music="F",
    )


def test_enforce_dialogue_removes_surplus_from_non_spoken_section():
    # Shot 1 mirror: the LLM wrote the line in both detailed_description and
    # overall_soundscape while the dialogue list has it once.
    sections = _six(
        desc="0-5s: dali recites '红豆生南国' to camera.",
        soundscape="The voice delivers the line '红豆生南国' with a calm tone.",
    )
    fixed = enforce_dialogue_occurrences_in_sections(sections, ["红豆生南国"])
    text = compose_h3_prompt(fixed)
    assert text.count("红豆生南国") == 1
    # the spoken occurrence in detailed_description is kept
    assert "红豆生南国" in fixed.detailed_description
    # the surplus mention in overall_soundscape is gone, prose stays grammatical
    assert "红豆生南国" not in fixed.overall_soundscape
    validate_h3_prompt(text, ["红豆生南国"])


def test_enforce_dialogue_is_idempotent():
    sections = _six(
        desc="dali recites '红豆生南国' to camera.",
        soundscape="The voice delivers the line '红豆生南国' calmly.",
    )
    once = enforce_dialogue_occurrences_in_sections(sections, ["红豆生南国"])
    twice = enforce_dialogue_occurrences_in_sections(once, ["红豆生南国"])
    assert once.overall_soundscape == twice.overall_soundscape
    assert compose_h3_prompt(twice).count("红豆生南国") == 1


def test_enforce_dialogue_adds_missing_occurrence():
    sections = _six(desc="dali looks at the tree.", soundscape="Quiet ambience.")
    fixed = enforce_dialogue_occurrences_in_sections(sections, ["红豆生南国"])
    text = compose_h3_prompt(fixed)
    assert text.count("红豆生南国") == 1
    assert "红豆生南国" in fixed.detailed_description
    validate_h3_prompt(text, ["红豆生南国"])


def test_enforce_dialogue_chorus_trims_extra_copy():
    sections = _six(
        desc="dali laughs hahaha, xiaobai laughs hahaha, then a third hahaha.",
    )
    fixed = enforce_dialogue_occurrences_in_sections(
        sections, ["hahaha", "hahaha"]
    )
    text = compose_h3_prompt(fixed)
    assert text.count("hahaha") == 2
    validate_h3_prompt(text, ["hahaha", "hahaha"])


def test_enforce_dialogue_keeps_exempt_direction_verbatim():
    direction = "GLOBAL DIRECTION: only two cats. The line 红豆生南国 is the theme."
    sections = PromptSections(
        subject_definitions=direction,
        summary="B",
        retention_analysis="C",
        detailed_description="dali recites '红豆生南国' to camera.",
        overall_soundscape="Quiet ambience.",
        non_diegetic_music="F",
    )
    fixed = enforce_dialogue_occurrences_in_sections(
        sections, ["红豆生南国"], exempt_text=direction
    )
    # the GLOBAL DIRECTION copy is untouched
    assert direction in fixed.subject_definitions
    # the surplus spoken copy is removed so the total matches the single dialogue
    text = compose_h3_prompt(fixed)
    assert text.count("红豆生南国") == 1
    assert "红豆生南国" not in fixed.detailed_description
    validate_h3_prompt(text, ["红豆生南国"])


def test_enforce_dialogue_noop_when_already_matching():
    sections = _six(desc="dali recites '红豆生南国' to camera.")
    fixed = enforce_dialogue_occurrences_in_sections(sections, ["红豆生南国"])
    assert fixed == sections


def test_enforce_dialogue_ignores_empty_dialogue():
    sections = _six()
    assert enforce_dialogue_occurrences_in_sections(sections, []) == sections


def test_audio_tags_must_reference_submitted_audio_but_may_repeat():
    sections = PromptSections(
        subject_definitions="<Audio 1> defines Mia. <Audio 2> defines Daniel.",
        summary="B",
        retention_analysis="C",
        detailed_description="Mia says hello.",
        overall_soundscape="E",
        non_diegetic_music="F",
    )
    text = compose_h3_prompt(sections)
    validate_h3_prompt(text, [], audio_count=2)
    validate_h3_prompt(
        text.replace("overall_soundscape:\nE", "overall_soundscape:\n<Audio 1> stays consistent."),
        [],
        audio_count=2,
    )

    with pytest.raises(ValueError, match="Audio 2"):
        validate_h3_prompt(text.replace("<Audio 2>", "Daniel"), [], audio_count=2)
    with pytest.raises(ValueError, match="Audio 3"):
        validate_h3_prompt(text + " <Audio 3>", [], audio_count=2)


def test_allows_picture_references_inside_timed_action_descriptions():
    sections = PromptSections(
        subject_definitions=(
            "<Picture 1> defines the rocket design. "
            "<Picture 2> defines the launch composition."
        ),
        summary="A rocket launches into the sky.",
        retention_analysis="Retain both references throughout the clip.",
        detailed_description=(
            "0.0-1.5s: The rocket stands in the composition established by "
            "<Picture 2> as its engines ignite. 1.5-3.3s: The rocket lifts "
            "while retaining the silhouette defined by <Picture 1>."
        ),
        overall_soundscape="A rising engine roar.",
        non_diegetic_music="No music.",
    )

    validate_h3_prompt(
        compose_h3_prompt(sections),
        [],
        required_picture_indices=[1, 2],
        submitted_picture_indices=[1, 2],
    )


def test_requires_every_selected_layout_picture_binding():
    from app.core.h3.prompt import validate_required_picture_bindings

    prompt = "<Picture 5> establishes the empty doorway."

    with pytest.raises(
        ValueError, match="missing selected Layout binding: <Picture 6>"
    ):
        validate_required_picture_bindings(prompt, [5, 6])


def test_required_picture_bindings_deduplicate_indices():
    from app.core.h3.prompt import validate_required_picture_bindings

    validate_required_picture_bindings(
        "<Picture 5> controls the composition.",
        [5, 5],
    )


def test_rejects_picture_tag_not_in_submitted_picture_set():
    from app.core.h3.prompt import validate_required_picture_bindings

    with pytest.raises(
        ValueError,
        match=r"unsubmitted Picture.*<Picture 3>",
    ):
        validate_required_picture_bindings(
            "<Picture 1> controls identity. <Picture 3> controls geography.",
            [],
            submitted_picture_indices=[1, 2],
        )


def _tail_transition_sections(detailed_description: str) -> PromptSections:
    return PromptSections(
        subject_definitions="<Picture 1> grounds the inherited vortex geometry.",
        summary="The inherited image state gives way to Mia.",
        retention_analysis="Retain coherent motion and Mia's identity.",
        detailed_description=detailed_description,
        overall_soundscape="A soft atmospheric swell.",
        non_diegetic_music="No music.",
    )


def _tail_transition_layouts() -> list[dict[str, object]]:
    return [
        {
            "asset_id": "lay_tail",
            "picture_index": 1,
            "origin_kind": "clip_tail_frame",
            "visible_transition_required": True,
        }
    ]


def test_allows_visible_tail_frame_handoff_in_first_action_interval():
    from app.core.h3.prompt import validate_tail_frame_transition_prompt

    validate_tail_frame_transition_prompt(
        _tail_transition_sections(
            "0–0.8 seconds: The inherited vortex continues, then dissolves open, "
            "revealing Mia's face. 0.8–5 seconds: Mia looks into camera."
        ),
        _tail_transition_layouts(),
    )


@pytest.mark.parametrize(
    "detailed_description",
    [
        "0–0.8 seconds: Hard cut to Mia's face. 0.8–5 seconds: She watches.",
        "0–0.8 seconds: Use the vortex as palette only. Mia watches.",
        "0–0.8 seconds: Use the vortex for style only. Mia watches.",
        "0–0.8 seconds: The inherited vortex must not manifest. Mia watches.",
        "0–0.8 seconds: The inherited vortex must not be visible. Mia watches.",
        "0.5–1.2 seconds: The inherited vortex dissolves to reveal Mia.",
        "0–0.8 seconds: Mia is already in close-up and looks into camera.",
    ],
)
def test_rejects_missing_or_neutralized_tail_frame_handoff(detailed_description):
    from app.core.h3.prompt import validate_tail_frame_transition_prompt

    with pytest.raises(ValueError, match="tail-frame transition"):
        validate_tail_frame_transition_prompt(
            _tail_transition_sections(detailed_description),
            _tail_transition_layouts(),
        )


def test_pipeline_enforces_required_layout_picture_binding():
    from app.core.schemas import JobRecord, JobStatus
    from app.pipelines.h3_ref2va.pipeline import H3Ref2VaPipeline

    prompt = compose_h3_prompt(
        PromptSections(
            subject_definitions="The doorway remains coherent.",
            summary="One coherent doorway scene.",
            retention_analysis="Retain geography.",
            detailed_description="From 0-5 seconds, Chen enters.",
            overall_soundscape="Room tone.",
            non_diegetic_music="No music.",
        )
    )
    job = JobRecord(
        id="job_layout_contract",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.queued,
        name="layout contract",
        params={
            "prompt": prompt,
            "dialogue": [],
            "frames": 90,
            "image_keys": ["ref_0"],
            "layout_picture_indices": [1],
        },
        created_at="2026-08-25T00:00:00+00:00",
        updated_at="2026-08-25T00:00:00+00:00",
    )

    with pytest.raises(
        ValueError,
        match="missing selected Layout binding: <Picture 1>",
    ):
        H3Ref2VaPipeline().build_prompt(
            job,
            uploaded_images={"ref_0": "layout.png"},
        )


def test_pipeline_rejects_picture_tag_beyond_actual_uploaded_image_order():
    from app.core.schemas import JobRecord, JobStatus
    from app.pipelines.h3_ref2va.pipeline import H3Ref2VaPipeline

    prompt = compose_h3_prompt(
        PromptSections(
            subject_definitions=(
                "<Picture 1> controls identity. <Picture 2> controls geography."
            ),
            summary="One coherent room scene.",
            retention_analysis="Retain identity and geography.",
            detailed_description="From 0-5 seconds, Chen enters.",
            overall_soundscape="Room tone.",
            non_diegetic_music="No music.",
        )
    )
    job = JobRecord(
        id="job_unsubmitted_picture",
        pipeline_id="h3_ref2va",
        asset_kind="productions",
        status=JobStatus.queued,
        name="unsubmitted Picture",
        params={
            "prompt": prompt,
            "dialogue": [],
            "frames": 90,
            "image_keys": ["ref_0"],
            "layout_picture_indices": [],
        },
        created_at="2026-08-25T00:00:00+00:00",
        updated_at="2026-08-25T00:00:00+00:00",
    )

    with pytest.raises(ValueError, match=r"unsubmitted Picture.*<Picture 2>"):
        H3Ref2VaPipeline().build_prompt(
            job,
            uploaded_images={"ref_0": "actor.png"},
        )
