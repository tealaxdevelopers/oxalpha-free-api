from fastapi import APIRouter, Depends, HTTPException, status
from app.api.deps import get_provider, verify_api_key
from app.models.openai import OpenAIModelCard, OpenAIModelList
from app.providers.base import AIProvider

router = APIRouter(dependencies=[Depends(verify_api_key)])


@router.get("/models", response_model=OpenAIModelList)
async def list_models(
    provider: AIProvider = Depends(get_provider),
) -> OpenAIModelList:
    """Return a list of models supported by the OxAlpha gateway."""
    canonical_list = await provider.list_models()
    return OpenAIModelList.from_canonical(canonical_list)


@router.get("/models/{model_id}", response_model=OpenAIModelCard)
async def retrieve_model(
    model_id: str,
    provider: AIProvider = Depends(get_provider),
) -> OpenAIModelCard:
    """Retrieve details of a specific model."""
    canonical_list = await provider.list_models()
    for m in canonical_list.data:
        if m.id.lower() == model_id.lower():
            return OpenAIModelCard(
                id=m.id,
                object=m.object,
                created=m.created,
                owned_by=m.owned_by,
            )
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"The model '{model_id}' does not exist.",
    )
