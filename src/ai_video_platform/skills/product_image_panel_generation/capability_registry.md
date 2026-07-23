# Product Image Panel Generation Capability Registry

| Capability | Proof chain | Status |
| --- | --- | --- |
| Warning-tolerant viral script input | `ViralScript.validate()` separates `submitted_context` warnings from identity/content blockers; contract gate asserts both channels | implemented |
| Product-as-data mapping | `to_product_facts()` projects the validated product payload into frozen `ProductFacts`; provider-field and immutability gates assert the boundary | implemented |
| Channel-aware product mode | `ChannelProfile.derive_product_mode()` applies explicit constraint, objective, format, then showcase precedence | implemented |
| ID-based reference resolution | `load_ref_image_paths_by_ids()` preserves requested order and rejects missing/non-local/non-image references | implemented |
| Bounded continuity-review media | PNG/JPEG dimension parsing enforces `IMAGE_MAX_EDGE=1792` and `IMAGE_MAX_BYTES=3MB` before assembly; rejection gate asserts clear errors | implemented |
| Narrative continuity propagation | `assemble_continuity_review()` -> `consume_continuity_review()` preserves `narrative_mode`, `lead_persona_ids`, and `scene_anchor_ids`; architecture gate asserts the seam | implemented |

## Anti-Forgery Record

The historical report references commits `50bb6c8`, `3d25c70`, and `dfe2fee`. Verification for Revision D found that these objects and the claimed Revision D branch/code did not exist. They are recorded here only as anti-forgery identifiers, not as implementation evidence or dependencies.
