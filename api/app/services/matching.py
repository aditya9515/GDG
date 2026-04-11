from __future__ import annotations

import math

from app.models.domain import (
    AvailabilityStatus,
    CaseRecord,
    GeoPoint,
    Recommendation,
    RecommendationReason,
    ResourceInventory,
    ResourceNeed,
    RouteSummary,
    Team,
    Volunteer,
)


def _distance(a: GeoPoint | None, b: GeoPoint | None) -> float | None:
    if a is None or b is None:
        return None
    radius = 6371.0
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlng = math.radians(b.lng - a.lng)
    calc = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(calc))


class MatchingService:
    def recommend(
        self,
        case: CaseRecord,
        teams: list[Team] | list[Volunteer],
        volunteers: list[Volunteer] | list[ResourceInventory],
        resources: list[ResourceInventory] | None = None,
        max_results: int = 3,
    ) -> tuple[list[Recommendation], str | None]:
        if case.extracted_json is None:
            return [], "Case must be extracted before recommendations can be generated."

        if resources is None:
            resources = volunteers  # type: ignore[assignment]
            volunteers = teams  # type: ignore[assignment]
            teams = self._teams_from_volunteers(volunteers)  # type: ignore[arg-type]

        feasible: list[tuple[Recommendation, tuple[float, float, float, float, str]]] = []
        required_skills = self._required_skills(case)
        available_resources = self._resource_allocations(case.extracted_json.required_resources, resources)  # type: ignore[arg-type]

        volunteer_lookup = {item.volunteer_id: item for item in volunteers}  # type: ignore[attr-defined]

        for team in teams:  # type: ignore[assignment]
            if team.availability_status == AvailabilityStatus.OFFLINE:
                continue
            members = [volunteer_lookup[item] for item in team.member_ids if item in volunteer_lookup]
            if not members:
                continue

            skill_match = self._team_capability_fit(required_skills, team, members)
            if skill_match <= 0:
                continue

            distance_km = _distance(case.geo, team.current_geo or team.base_geo)
            eta_minutes = None if distance_km is None else max(8, int((distance_km / 35) * 60))
            eta_score = self._eta_score(eta_minutes)
            availability = 1.0 if team.availability_status == AvailabilityStatus.AVAILABLE else 0.6
            capacity_ok = 1.0 if team.active_dispatches < max(len(members), 1) else 0.0
            if capacity_ok == 0.0:
                continue
            workload_balance = max(0.0, 1.0 - (team.active_dispatches / max(len(members), 1)))
            reliability = team.reliability_score
            match_score = round(
                0.35 * skill_match
                + 0.25 * eta_score
                + 0.15 * availability
                + 0.10 * capacity_ok
                + 0.10 * workload_balance
                + 0.05 * reliability,
                3,
            )

            selected_members = [
                member.volunteer_id
                for member in sorted(
                    members,
                    key=lambda item: (
                        item.active_assignments,
                        -item.reliability_score,
                        item.volunteer_id,
                    ),
                )[: min(2, len(members))]
            ]

            recommendation = Recommendation(
                team_id=team.team_id,
                volunteer_ids=selected_members,
                resource_ids=[item.resource_id for item in self._resource_matches(case.extracted_json.required_resources, resources)],
                resource_allocations=available_resources,
                match_score=match_score,
                eta_minutes=eta_minutes,
                route_summary=RouteSummary(
                    provider="fallback",
                    distance_km=distance_km,
                    duration_minutes=eta_minutes,
                ),
                reasons=[
                    RecommendationReason(
                        entity_id=team.team_id,
                        label=team.display_name,
                        capability_fit=round(skill_match, 3),
                        eta_score=round(eta_score, 3),
                        availability=availability,
                        capacity_ok=capacity_ok,
                        workload_balance=round(workload_balance, 3),
                        reliability=reliability,
                    )
                ],
            )
            feasible.append(
                (
                    recommendation,
                    (
                        round(skill_match, 3),
                        eta_score,
                        workload_balance,
                        reliability,
                        team.team_id,
                    ),
                )
            )

        feasible.sort(key=lambda item: (item[0].match_score, *item[1]), reverse=True)
        if not feasible:
            return [], "No feasible team/resource combination is available right now."
        return [item[0] for item in feasible[:max_results]], None

    def _required_skills(self, case: CaseRecord) -> set[str]:
        extraction = case.extracted_json
        if extraction is None:
            return set()
        skills = {str(extraction.category), extraction.subcategory}
        for resource in extraction.required_resources:
            skills.add(resource.resource_type)
        if str(extraction.category) == "RESCUE":
            skills.update({"RESCUE", "EVACUATION"})
        if str(extraction.category) == "MEDICAL":
            skills.update({"FIRST_AID", "MEDICAL"})
        if str(extraction.category) in {"WATER", "SANITATION"}:
            skills.update({"WASH", "LOGISTICS"})
        return {skill.upper() for skill in skills}

    def _resource_matches(self, needs: list[ResourceNeed], inventory: list[ResourceInventory]) -> list[ResourceInventory]:
        matches: list[ResourceInventory] = []
        for need in needs:
            for resource in inventory:
                if resource.resource_type != need.resource_type:
                    continue
                if resource.quantity_available <= 0:
                    continue
                matches.append(resource)
                break
        return matches

    def _resource_allocations(self, needs: list[ResourceNeed], inventory: list[ResourceInventory]) -> list[ResourceNeed]:
        allocations: list[ResourceNeed] = []
        for need in needs:
            for resource in inventory:
                if resource.resource_type != need.resource_type:
                    continue
                if resource.quantity_available <= 0:
                    continue
                allocations.append(
                    ResourceNeed(
                        resource_type=need.resource_type,
                        quantity=min(need.quantity or 1, resource.quantity_available),
                        unit=need.unit,
                    )
                )
                break
        return allocations

    def _teams_from_volunteers(self, volunteers: list[Volunteer]) -> list[Team]:
        grouped: dict[str, Team] = {}
        for volunteer in volunteers:
            team_id = volunteer.team_id or f"TEAM-{volunteer.volunteer_id[-3:]}"
            if team_id not in grouped:
                grouped[team_id] = Team(
                    team_id=team_id,
                    display_name=volunteer.display_name,
                    capability_tags=[],
                    member_ids=[],
                    service_radius_km=45,
                    base_label=volunteer.home_base_label,
                    base_geo=volunteer.home_base,
                    current_label=volunteer.home_base_label,
                    current_geo=volunteer.current_geo or volunteer.home_base,
                    availability_status=volunteer.availability_status,
                    active_dispatches=0,
                    reliability_score=volunteer.reliability_score,
                )
            team = grouped[team_id]
            team.member_ids.append(volunteer.volunteer_id)
            team.capability_tags = sorted(set(team.capability_tags + volunteer.role_tags + volunteer.skills))
            team.active_dispatches += volunteer.active_assignments
            grouped[team_id] = team
        return list(grouped.values())

    def _team_capability_fit(self, required: set[str], team: Team, members: list[Volunteer]) -> float:
        if not required:
            return 0.0
        team_skills = {skill.upper() for skill in team.capability_tags}
        member_skills = {skill.upper() for member in members for skill in [*member.skills, *member.role_tags]}
        available = team_skills | member_skills
        return len(required & available) / len(required)

    def _eta_score(self, eta_minutes: int | None) -> float:
        if eta_minutes is None:
            return 0.35
        if eta_minutes <= 15:
            return 1.0
        if eta_minutes <= 60:
            return 0.5
        if eta_minutes >= 180:
            return 0.0
        return round(1 - ((eta_minutes - 15) / 165), 3)
