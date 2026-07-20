"""Pure deterministic analysis algorithms for explicitly selected references."""

from __future__ import annotations

from collections import Counter
import math
from typing import Mapping, Sequence

from .errors import ErrorCode, SkillError


ALGORITHM_VERSION = "1.0.0"


def _number(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment time must be finite", field_paths=(field,))
    return float(value)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment field must be non-empty text", field_paths=(field,))
    return value.strip()


def summarize_segments(segments: object) -> dict[str, object]:
    if not isinstance(segments, Sequence) or isinstance(segments, (str, bytes)) or not segments:
        raise SkillError(ErrorCode.VALIDATION_FAILED, "segments must be a non-empty array", field_paths=("segments",))
    shots: Counter[str] = Counter()
    emotions: Counter[str] = Counter()
    motifs: Counter[str] = Counter()
    hook_positions: list[float] = []
    cta_positions: list[float] = []
    durations: list[float] = []
    prior_end = 0.0
    for index, raw in enumerate(segments):
        if not isinstance(raw, Mapping):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segment must be an object", field_paths=(f"segments[{index}]",))
        start = _number(raw.get("start"), f"segments[{index}].start")
        end = _number(raw.get("end"), f"segments[{index}].end")
        if start < 0 or end <= start or start < prior_end:
            raise SkillError(ErrorCode.VALIDATION_FAILED, "Segments must be ordered, non-overlapping, and positive", field_paths=(f"segments[{index}]",))
        shot = _text(raw.get("shot_type"), f"segments[{index}].shot_type")
        emotion = _text(raw.get("emotion"), f"segments[{index}].emotion")
        raw_motifs = raw.get("visual_motifs")
        if not isinstance(raw_motifs, Sequence) or isinstance(raw_motifs, (str, bytes)):
            raise SkillError(ErrorCode.VALIDATION_FAILED, "visual_motifs must be an array", field_paths=(f"segments[{index}].visual_motifs",))
        normalized_motifs = tuple(_text(motif, f"segments[{index}].visual_motifs") for motif in raw_motifs)
        for flag in ("is_hook", "is_cta"):
            if flag in raw and not isinstance(raw[flag], bool):
                raise SkillError(ErrorCode.VALIDATION_FAILED, f"{flag} must be boolean", field_paths=(f"segments[{index}].{flag}",))
        durations.append(end - start)
        shots[shot] += 1
        emotions[emotion] += 1
        motifs.update(normalized_motifs)
        if raw.get("is_hook") is True:
            hook_positions.append(start)
        if raw.get("is_cta") is True:
            cta_positions.append(start)
        prior_end = end
    total_duration = prior_end
    count = len(durations)
    return {
        "segment_count": count,
        "total_duration": round(total_duration, 6),
        "average_segment_duration": round(sum(durations) / count, 6),
        "cuts_per_second": round(count / total_duration, 6),
        "shot_distribution": dict(sorted(shots.items())),
        "emotion_distribution": dict(sorted(emotions.items())),
        "visual_motifs": dict(sorted(motifs.items())),
        "hook_positions": hook_positions,
        "cta_positions": cta_positions,
    }


def compare_metrics(reference: Mapping[str, object], produced: Mapping[str, object]) -> dict[str, object]:
    scalar_names = ("segment_count", "total_duration", "average_segment_duration", "cuts_per_second")
    deltas: dict[str, float] = {}
    gaps: list[dict[str, object]] = []
    for name in scalar_names:
        reference_value = float(reference[name])
        produced_value = float(produced[name])
        delta = round(produced_value - reference_value, 6)
        deltas[name] = delta
        normalized = abs(delta) / max(abs(reference_value), 1.0)
        gaps.append({"metric": name, "delta": delta, "severity_rank": int(round(normalized * 1000))})
    reference_motifs = set(reference["visual_motifs"])
    produced_motifs = set(produced["visual_motifs"])
    missing_motifs = sorted(reference_motifs - produced_motifs)
    if missing_motifs:
        gaps.append({"metric": "missing_motifs", "delta": len(missing_motifs), "severity_rank": len(missing_motifs) * 1000})
    gaps.sort(key=lambda item: (-int(item["severity_rank"]), str(item["metric"])))
    return {
        "metric_deltas": deltas,
        "missing_motifs": missing_motifs,
        "shot_gaps": _distribution_gap(reference["shot_distribution"], produced["shot_distribution"]),
        "emotion_gaps": _distribution_gap(reference["emotion_distribution"], produced["emotion_distribution"]),
        "ordered_gaps": gaps,
    }


def _distribution_gap(reference: object, produced: object) -> dict[str, int]:
    reference_map = dict(reference) if isinstance(reference, Mapping) else {}
    produced_map = dict(produced) if isinstance(produced, Mapping) else {}
    return {
        key: int(produced_map.get(key, 0)) - int(reference_map.get(key, 0))
        for key in sorted(set(reference_map) | set(produced_map))
    }
