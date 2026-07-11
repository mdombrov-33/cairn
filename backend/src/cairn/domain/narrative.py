"""Narrative identity and companion-owned JSONB shapes."""

from typing import Literal, NotRequired, Required, TypedDict

NpcTier = Literal["major", "recurring", "background"]


class NarrativeVoice(TypedDict, total=False):
    accent: str
    pace: str
    vocabulary: str
    speech_quirks: list[str]


class NarrativeGoals(TypedDict, total=False):
    immediate: str
    midterm: str
    life: str


class NarrativeRelationship(TypedDict, total=False):
    name: str
    relation: str
    status: str
    notes: str


class NarrativeProfile(TypedDict, total=False):
    name: Required[str]
    personality: Required[str]
    voice: Required[NarrativeVoice]
    race: str
    age: int
    profession: str
    physical: str
    backstory: str
    goals: NarrativeGoals
    prejudices: list[str]
    relationships: list[NarrativeRelationship]
    private_facts: list[str]


class ApprovalLogEntry(TypedDict):
    turn_id: str
    delta: int
    reason: str
    total: int


class CompanionMeta(TypedDict, total=False):
    approval: int
    mood: str
    personal_goal: str
    secret: str | None
    approval_log: list[ApprovalLogEntry]


class ApprovalDelta(TypedDict):
    companion_id: str
    delta: int
    reason: str


class DialogueEntity(TypedDict):
    name: str
    profile: NarrativeProfile
    disposition: str
    approval_band: NotRequired[str]
    mood: NotRequired[str]
