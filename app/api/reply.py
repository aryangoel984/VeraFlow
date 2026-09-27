from fastapi import APIRouter

from app.engine.conversation import handle_reply
from app.models.schemas import ReplyRequest, ReplyResponse
from app.storage.state import state

router = APIRouter()


@router.post("/v1/reply", response_model=ReplyResponse)
async def reply(body: ReplyRequest) -> ReplyResponse:
    conv = state.get_or_create_conversation(
        body.conversation_id, merchant_id=body.merchant_id, customer_id=body.customer_id,
    )
    if conv.status == "ended":
        return ReplyResponse(action="end", rationale="Conversation was already closed; ignoring further replies.")

    result = await handle_reply(conv, body.message, state)
    return ReplyResponse(**result)
