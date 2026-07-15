"""Pure campaign lifecycle policy."""

from typing import Literal

CampaignStatus = Literal["active", "completed", "ended_dead"]
CampaignOperation = Literal["read", "mutate", "delete"]

_ALLOWED_OPERATIONS: dict[str, frozenset[CampaignOperation]] = {
    "active": frozenset({"read", "mutate", "delete"}),
    "completed": frozenset({"read", "delete"}),
    "ended_dead": frozenset({"read", "delete"}),
}


def allows_campaign_operation(status: str, operation: CampaignOperation) -> bool:
    """Return whether a campaign lifecycle status permits an operation."""
    return operation in _ALLOWED_OPERATIONS.get(status, frozenset())


def is_campaign_mutable(status: str) -> bool:
    """Whether player play-state mutations are permitted for this campaign."""
    return allows_campaign_operation(status, "mutate")
