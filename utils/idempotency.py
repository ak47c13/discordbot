"""
Discord interaction idempotency.
Before processing any state-changing slash command, check if the interaction_id
was already handled. If yes, re-send the cached reply and return early.
"""
from models.processed_interaction import ProcessedInteraction


async def is_already_processed(interaction_id: str) -> bool:
    existing = await ProcessedInteraction.find_one(
        ProcessedInteraction.interaction_id == interaction_id
    )
    return existing is not None


async def mark_processed(interaction_id: str, summary: str = "") -> None:
    record = ProcessedInteraction(
        interaction_id=interaction_id,
        result_summary=summary,
    )
    await record.insert()
