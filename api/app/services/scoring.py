from __future__ import annotations

from app.models.domain import CategoryKind, IncidentExtraction, PriorityRationale, UrgencyKind, VulnerableGroup


class ScoringService:
    def score(self, extraction: IncidentExtraction) -> PriorityRationale:
        s1 = self._life_threat_score(extraction)
        s2 = self._time_sensitivity_score(extraction)
        s3 = self._vulnerability_score(extraction)
        s4 = self._scale_score(extraction)
        s5 = self._sector_severity_score(extraction)
        s6 = self._access_constraint_score(extraction)
        final_score = round(100 * (0.35 * s1 + 0.20 * s2 + 0.15 * s3 + 0.10 * s4 + 0.10 * s5 + 0.10 * s6), 2)
        final_urgency = self._map_urgency(final_score)
        cap_reason = None

        if extraction.confidence < 0.4 or (
            extraction.data_quality.missing_location and not extraction.location_text and extraction.time_to_act_hours is None
        ):
            final_urgency = UrgencyKind.UNKNOWN
            cap_reason = "Low confidence or missing location and timing details."
        elif extraction.data_quality.missing_location and final_urgency == UrgencyKind.CRITICAL:
            final_urgency = UrgencyKind.HIGH
            cap_reason = "Urgency capped at HIGH until the location is verified."

        return PriorityRationale(
            life_threat_score=s1,
            time_sensitivity_score=s2,
            vulnerability_score=s3,
            scale_score=s4,
            sector_severity_score=s5,
            access_constraint_score=s6,
            final_score=final_score,
            final_urgency=final_urgency,
            cap_reason=cap_reason,
        )

    def _map_urgency(self, score: float) -> UrgencyKind:
        if score >= 80:
            return UrgencyKind.CRITICAL
        if score >= 60:
            return UrgencyKind.HIGH
        if score >= 35:
            return UrgencyKind.MEDIUM
        return UrgencyKind.LOW

    def _life_threat_score(self, extraction: IncidentExtraction) -> float:
        if extraction.urgency == UrgencyKind.CRITICAL:
            return 1.0
        if extraction.category == CategoryKind.RESCUE:
            return 0.95
        if extraction.subcategory in {
            "MATERNAL_EMERGENCY_TRANSPORT",
            "TRAUMA_MULTI_CASUALTY",
            "BLOOD_REQUIREMENT",
            "SNAKEBITE_REFERRAL",
        }:
            return 1.0
        return 0.6 if extraction.category == CategoryKind.MEDICAL else 0.2

    def _time_sensitivity_score(self, extraction: IncidentExtraction) -> float:
        if extraction.time_to_act_hours is None:
            return 0.4
        hours = extraction.time_to_act_hours
        if hours <= 2:
            return 1.0
        if hours <= 6:
            return 0.85
        if hours <= 12:
            return 0.7
        if hours <= 24:
            return 0.5
        if hours <= 48:
            return 0.3
        return 0.1

    def _vulnerability_score(self, extraction: IncidentExtraction) -> float:
        groups = set(extraction.vulnerable_groups)
        if not groups or groups == {VulnerableGroup.NONE}:
            return 0.0
        weight = 0.25
        if VulnerableGroup.PREGNANT in groups:
            weight += 0.35
        if VulnerableGroup.CHILDREN_UNDER5 in groups:
            weight += 0.2
        if VulnerableGroup.ELDERLY in groups:
            weight += 0.2
        if VulnerableGroup.CHRONIC_ILLNESS in groups:
            weight += 0.2
        return min(weight, 1.0)

    def _scale_score(self, extraction: IncidentExtraction) -> float:
        people = extraction.people_affected or 1
        if people >= 100:
            return 1.0
        if people >= 30:
            return 0.75
        if people >= 10:
            return 0.55
        if people >= 3:
            return 0.35
        return 0.1

    def _sector_severity_score(self, extraction: IncidentExtraction) -> float:
        if extraction.category in {CategoryKind.WATER, CategoryKind.SANITATION, CategoryKind.MEDICAL, CategoryKind.RESCUE}:
            return 0.9
        if extraction.category in {CategoryKind.SHELTER, CategoryKind.FOOD, CategoryKind.PROTECTION}:
            return 0.7
        return 0.45

    def _access_constraint_score(self, extraction: IncidentExtraction) -> float:
        notes = f"{extraction.location_text} {extraction.notes_for_dispatch}".lower()
        tokens = (
            "blocked",
            "waterlogged",
            "collapsed",
            "no network",
            "cut off",
            "alternate route",
            "rising water",
            "rooftop",
        )
        return 0.9 if any(token in notes for token in tokens) else 0.35
