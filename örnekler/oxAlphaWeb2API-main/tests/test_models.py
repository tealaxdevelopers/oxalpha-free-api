import pytest
import httpx
from app.models.canonical import ModelCard, ModelList
from app.models.openai import OpenAIModelList


@pytest.mark.asyncio
async def test_list_models(client: httpx.AsyncClient):
    resp = await client.get("/v1/models")
    assert resp.status_code == 200
    data = resp.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    assert len(data["data"]) >= 1

    model_ids = [m["id"] for m in data["data"]]
    assert "oxalpha" in model_ids
    assert "z-ai/glm-5.3-flash" in model_ids

    # Verify model fields
    first = data["data"][0]
    assert first["object"] == "model"
    assert "created" in first
    assert "owned_by" in first


@pytest.mark.asyncio
async def test_retrieve_model_found(client: httpx.AsyncClient):
    resp = await client.get("/v1/models/oxalpha")
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == "oxalpha"
    assert data["object"] == "model"
    assert data["owned_by"] == "oxalpha"


@pytest.mark.asyncio
async def test_retrieve_model_not_found(client: httpx.AsyncClient):
    resp = await client.get("/v1/models/unknown-model-xyz")
    assert resp.status_code == 404
    data = resp.json()
    assert "error" in data
    assert data["error"]["type"] == "invalid_request_error"


def test_canonical_model_list_conversion():
    cards = [
        ModelCard(id="test-1", object="model", created=123, owned_by="test"),
        ModelCard(id="test-2", object="model", created=456, owned_by="test"),
    ]
    model_list = ModelList(object="list", data=cards)
    openai_list = OpenAIModelList.from_canonical(model_list)
    assert openai_list.object == "list"
    assert len(openai_list.data) == 2
    assert openai_list.data[0].id == "test-1"
