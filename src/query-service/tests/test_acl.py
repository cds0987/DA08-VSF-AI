import pytest

from app.infrastructure.db.mock_document_access_repo import InMemoryDocumentAccessRepository


@pytest.mark.asyncio
async def test_acl_filters_documents_by_classification():
    repo = InMemoryDocumentAccessRepository()

    hr_docs = await repo.get_allowed_doc_ids(
        user_id="11111111-1111-4111-8111-111111111111",
        role="user",
        department="HR",
    )
    finance_docs = await repo.get_allowed_doc_ids(
        user_id="22222222-2222-4222-8222-222222222222",
        role="user",
        department="Finance",
    )
    admin_docs = await repo.get_allowed_doc_ids(
        user_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        role="admin",
        department="Admin",
    )

    assert "dddddddd-0001-4000-8000-000000000001" in hr_docs
    assert "dddddddd-0002-4000-8000-000000000002" in hr_docs
    assert "dddddddd-0003-4000-8000-000000000003" not in hr_docs
    assert "dddddddd-0003-4000-8000-000000000003" in finance_docs
    assert "dddddddd-0004-4000-8000-000000000004" not in finance_docs
    assert "dddddddd-0004-4000-8000-000000000004" in admin_docs


@pytest.mark.asyncio
async def test_acl_projection_upsert_and_delete():
    repo = InMemoryDocumentAccessRepository()
    doc_id = "eeeeeeee-0001-4000-8000-000000000001"

    await repo.upsert_access(
        document_id=doc_id,
        classification="secret",
        allowed_departments=["HR"],
        allowed_user_ids=[],
    )
    hr_docs = await repo.get_allowed_doc_ids(
        user_id="11111111-1111-4111-8111-111111111111",
        role="user",
        department="HR",
    )
    finance_docs = await repo.get_allowed_doc_ids(
        user_id="22222222-2222-4222-8222-222222222222",
        role="user",
        department="Finance",
    )

    assert doc_id in hr_docs
    assert doc_id not in finance_docs

    await repo.delete_access(doc_id)
    hr_docs_after_delete = await repo.get_allowed_doc_ids(
        user_id="11111111-1111-4111-8111-111111111111",
        role="user",
        department="HR",
    )
    assert doc_id not in hr_docs_after_delete
