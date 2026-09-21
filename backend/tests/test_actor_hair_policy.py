"""Actor workbench: reference → master + multipanel three-view (no body/hair split)."""

from app.pipelines.actor import workflow as w


def test_ref_master_uses_full_identity():
    assert "REFERENCE photo" in w.REF_ACTOR_MASTER_PROMPT
    assert "Preserve the same person" in w.REF_ACTOR_MASTER_PROMPT
    assert "USER DESCRIPTION" in w.REF_ACTOR_MASTER_PROMPT or "written description" in w.REF_ACTOR_MASTER_PROMPT
    assert w.REF_FACE_ONLY_MASTER_PROMPT == w.REF_ACTOR_MASTER_PROMPT


def test_build_appends_description_into_ref_master():
    graph, _ = w.build_actor_prompt(
        description="bare feet, no shoes",
        actor_image_name="face.png",
    )
    ref_prompt = graph["63"]["inputs"]["value"]
    assert "USER DESCRIPTION:" in ref_prompt
    assert "bare feet, no shoes" in ref_prompt
    # must not hard-force shoes over user text
    assert "Wear simple closed shoes" not in ref_prompt


def test_fullbody_prompt_matches_0081_baseline():
    # Same multipanel language as working job 008126d9
    assert "Image 1 is the actor MASTER (full-body front)" in w.FULLBODY_THREEVIEW_PROMPT
    assert "original actor REFERENCE photo" in w.FULLBODY_THREEVIEW_PROMPT
    assert "exactly THREE equal vertical panels" in w.FULLBODY_THREEVIEW_PROMPT
    assert "LEFT: exact front view" in w.FULLBODY_THREEVIEW_PROMPT
    assert "RIGHT: exact back view" in w.FULLBODY_THREEVIEW_PROMPT
    assert "side view" not in w.DEFAULT_NEGATIVE


def test_build_feeds_ref_into_master_and_threeview():
    graph, seed = w.build_actor_prompt(
        description="test actor with long hair",
        body_description="IGNORED tall",
        hair_description="IGNORED bun",
        actor_image_name="face.png",
    )
    # body/hair tracks cleared
    assert graph["59"]["inputs"]["value"] == ""
    assert graph["60"]["inputs"]["value"] == ""
    assert "test actor" in graph["58"]["inputs"]["value"]
    # master ref path uses actor image
    assert graph["15"]["inputs"]["image"] == "face.png"
    assert graph["16"]["inputs"]["image1"] == [w.NODE_ACTOR_IMAGE, 0]
    assert graph["63"]["inputs"]["value"].startswith(w.REF_ACTOR_MASTER_PROMPT)
    assert "USER DESCRIPTION:" in graph["63"]["inputs"]["value"]
    assert "test actor with long hair" in graph["63"]["inputs"]["value"]
    # three-view multipanel: master + actor ref
    assert graph["40"]["inputs"]["image1"] == ["30", 0]
    assert graph["40"]["inputs"]["image2"] == [w.NODE_ACTOR_IMAGE, 0]
    assert graph["46"]["inputs"]["images"] == ["45", 0]
    assert graph["32"]["inputs"]["image"] == ["45", 0]
    assert "200" not in graph
    assert seed is not None


def test_build_feeds_original_actor_ref_into_wardrobe_identity_lock():
    graph, _ = w.build_actor_prompt(
        description="test actor",
        actor_image_name="face.png",
        wardrobe_image_name="coat.png",
    )

    wardrobe = graph["24"]["inputs"]
    assert wardrobe["image1"] == ["22", 0]
    assert wardrobe["image2"] == ["56", 0]
    assert wardrobe["image3"] == [w.NODE_ACTOR_IMAGE, 0]
    assert "Image 3 is the original actor reference" in wardrobe["prompt"]
    assert "identity only" in wardrobe["prompt"]


def test_wardrobe_headwear_and_footwear_are_opt_in():
    graph, _ = w.build_actor_prompt(
        description="test actor",
        actor_image_name="face.png",
        wardrobe_image_name="coat.png",
    )

    extraction = graph[w.NODE_WARDROBE_EXTRACT_PROMPT]["inputs"]["prompt"]
    transfer = graph["24"]["inputs"]["prompt"]
    assert "Exclude headwear" in extraction
    assert "Exclude shoes and other footwear" in extraction
    assert "do not add headwear" in transfer
    assert "if the master is barefoot, keep it barefoot" in transfer
    threeview = graph[w.NODE_FULLBODY_THREEVIEW_PROMPT]["inputs"]["value"]
    assert "No hat or headwear in any panel" in threeview
    assert "headwear (if present)" not in threeview


def test_build_can_extract_and_apply_headwear_and_footwear():
    graph, _ = w.build_actor_prompt(
        description="test actor",
        actor_image_name="face.png",
        wardrobe_image_name="pirate.png",
        include_headwear=True,
        include_footwear=True,
    )

    extraction = graph[w.NODE_WARDROBE_EXTRACT_PROMPT]["inputs"]["prompt"]
    transfer = graph["24"]["inputs"]["prompt"]
    assert "Include clearly visible hat or headwear" in extraction
    assert "Include clearly visible shoes or boots" in extraction
    assert "Apply the hat or headwear from image 2" in transfer
    assert "Apply the exact footwear from image 2" in transfer
    assert "if the master is barefoot, keep it barefoot" not in transfer
    threeview = graph[w.NODE_FULLBODY_THREEVIEW_PROMPT]["inputs"]["value"]
    assert "The same hat or headwear visible on the master must appear in all three panels" in threeview
    assert "No hat or headwear in any panel" not in threeview


def test_derive_mode_reference():
    assert w.derive_mode(has_actor_ref=True, has_wardrobe_ref=False) == "reference"
    assert w.derive_mode(has_actor_ref=False, has_wardrobe_ref=False) == "text"


def test_build_uses_uploaded_blank_for_missing_references():
    graph, _ = w.build_actor_prompt(
        description="fairy with long hair",
        blank_image_name="ds_job_actor_blank.png",
    )

    assert graph["15"]["inputs"]["image"] == "ds_job_actor_blank.png"
    assert graph["23"]["inputs"]["image"] == "ds_job_actor_blank.png"


def test_quadruped_species_drives_the_text_path_master():
    graph, _ = w.build_actor_prompt(
        description="Dali, a ginger tabby cat with stripes",
        species=w.SPECIES_QUADRUPED,
    )

    # Text path master (58 → 62 → 10) must carry the animal anatomy block.
    assert graph["58"]["inputs"]["value"].startswith(w.TEXT_QUADRUPED_MASTER_PROMPT)
    assert "Dali, a ginger tabby cat with stripes" in graph["58"]["inputs"]["value"]
    assert "no anthropomorphic posture" in graph["58"]["inputs"]["value"]
    # Three-view and negatives stay quadruped-aware.
    assert "animal actor MASTER" in graph["66"]["inputs"]["value"]
    assert "anthropomorphic" in graph["11"]["inputs"]["text"]


def test_quadruped_master_ignores_human_boilerplate_description():
    graph, _ = w.build_actor_prompt(
        description=w.DEFAULT_DESCRIPTION,
        species=w.SPECIES_QUADRUPED,
    )

    text_value = graph["58"]["inputs"]["value"]
    assert w.DEFAULT_QUADRUPED_DESCRIPTION in text_value
    assert "standing upright" not in text_value
    assert "exactly one person" not in text_value

    ref_value = graph["63"]["inputs"]["value"]
    assert "standing upright" not in ref_value
    assert "exactly one person" not in ref_value


def test_human_and_auto_species_keep_the_plain_text_description():
    human, _ = w.build_actor_prompt(description="a woman", species=w.SPECIES_HUMAN)
    assert human["58"]["inputs"]["value"] == "a woman"

    auto_cat, _ = w.build_actor_prompt(description="a ginger cat", species=w.SPECIES_AUTO)
    assert auto_cat["58"]["inputs"]["value"].startswith(w.TEXT_QUADRUPED_MASTER_PROMPT)


def test_resolve_actor_identity_fills_species_appropriate_default():
    species, description = w.resolve_actor_identity(
        {"species": "quadruped", "description": ""}
    )
    assert species == w.SPECIES_QUADRUPED
    assert description == w.DEFAULT_QUADRUPED_DESCRIPTION

    species, description = w.resolve_actor_identity(
        {"species": "quadruped", "description": w.DEFAULT_DESCRIPTION}
    )
    assert species == w.SPECIES_QUADRUPED
    # The human casting boilerplate must never ride along on a quadruped.
    assert description == w.DEFAULT_QUADRUPED_DESCRIPTION


def test_actor_prompt_identity_drops_human_boilerplate_for_a_quadruped():
    appearance, species = w.actor_prompt_identity(
        {"species": "quadruped", "description": w.DEFAULT_DESCRIPTION}
    )
    assert species == w.SPECIES_QUADRUPED
    assert appearance == w.DEFAULT_QUADRUPED_DESCRIPTION
    assert "person" not in appearance.lower()

    appearance, species = w.actor_prompt_identity(
        {"species": "human", "description": "Mia, a tall woman with red hair"}
    )
    assert species == w.SPECIES_HUMAN
    assert appearance == "Mia, a tall woman with red hair"

    # Human actors are untouched, including the generic casting boilerplate.
    appearance, species = w.actor_prompt_identity(
        {"species": "human", "description": w.DEFAULT_DESCRIPTION}
    )
    assert species == w.SPECIES_HUMAN
    assert appearance == w.DEFAULT_DESCRIPTION


def test_no_wardrobe_forces_natural_coat_and_skips_negatives():
    graph, _ = w.build_actor_prompt(
        description="Dali, a ginger tabby cat with stripes",
        species=w.SPECIES_QUADRUPED,
        include_wardrobe=False,
    )

    assert w.NO_WARDROBE_INSTRUCTION in graph["58"]["inputs"]["value"]
    assert w.NO_WARDROBE_INSTRUCTION in graph["63"]["inputs"]["value"]
    assert "natural coat only" in graph["66"]["inputs"]["value"]
    assert "clothing" in graph["11"]["inputs"]["text"]

    default, _ = w.build_actor_prompt(
        description="Dali, a ginger tabby cat with stripes",
        species=w.SPECIES_QUADRUPED,
    )
    assert w.NO_WARDROBE_INSTRUCTION not in default["58"]["inputs"]["value"]
    assert "clothing" not in default["11"]["inputs"]["text"]


def test_actor_pipeline_drops_wardrobe_output_when_not_needed():
    from app.core.schemas import JobRecord, JobStatus
    from app.pipelines.actor.pipeline import ActorPipeline

    history = {
        "outputs": {
            "57": {"images": [{"filename": "w.png", "subfolder": "", "type": "output"}]},
            "31": {"images": [{"filename": "m.png", "subfolder": "", "type": "output"}]},
        }
    }

    def job(include_wardrobe: bool) -> JobRecord:
        return JobRecord(
            id="job_wardrobe",
            pipeline_id="actor",
            asset_kind="actors",
            status=JobStatus.succeeded,
            name="test",
            params={"include_wardrobe": include_wardrobe},
            created_at="2026-01-01T00:00:00Z",
            updated_at="2026-01-01T00:00:00Z",
        )

    with_wardrobe = ActorPipeline().map_history_outputs(history, job=job(True))
    assert "wardrobe_ref" in with_wardrobe

    without = ActorPipeline().map_history_outputs(history, job=job(False))
    assert "wardrobe_ref" not in without
    assert "master" in without


def test_actor_default_inputs_ships_a_valid_one_by_one_png():
    from app.pipelines.actor.pipeline import ActorPipeline

    inputs = ActorPipeline().default_inputs()
    filename, data = inputs[w.BLANK_INPUT_KEY]

    assert filename.endswith(".png")
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    # IHDR width/height immediately follow the 8-byte signature, 4-byte length
    # and 4-byte chunk type: both must be 1 so the graph's size switch reads
    # this as "no upload".
    assert data[16:20] == b"\x00\x00\x00\x01"
    assert data[20:24] == b"\x00\x00\x00\x01"
