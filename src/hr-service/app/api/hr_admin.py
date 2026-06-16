from __future__ import annotations
import datetime
import logging
from collections.abc import AsyncGenerator
from typing import Any, Optional, Literal, Set

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator

from app.api.auth import require_admin_jwt
from app.core.config import HrSettings, get_settings
from app.domain.repositories.hr_repository import HrRepository
from app.application.use_cases.list_employees_use_case import ListEmployeesUseCase
from app.application.use_cases.get_employee_use_case import GetEmployeeUseCase
from app.application.use_cases.update_employee_use_case import UpdateEmployeeUseCase
from app.application.services.employee_profile_service import EmployeeProfileService

logger = logging.getLogger("hr-admin")

admin_router = APIRouter(
    prefix="/hr/admin",
    tags=["hr-admin"],
    dependencies=[Depends(require_admin_jwt)],
)

# --- Schemas ---
class EmployeeItem(BaseModel):
    id: str
    user_id: str
    employee_code: str | None
    company_email: str
    department: str
    job_title: str | None
    manager_user_id: str | None
    employment_status: str
    full_name: str | None = None
    phone_number: str | None = None
    date_of_birth: datetime.date | None = None
    hire_date: datetime.date | None = None
    created_at: datetime.datetime
    updated_at: datetime.datetime

class EmployeeListResponse(BaseModel):
    items: list[EmployeeItem]
    total: int

class UpdateEmployeeRequest(BaseModel):
    employee_code: Optional[str] = None
    job_title: Optional[str] = None
    manager_user_id: Optional[str] = None
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    date_of_birth: Optional[datetime.date] = None
    hire_date: Optional[datetime.date] = None
    department: Optional[str] = None

    @field_validator(
        "employee_code", "job_title", "manager_user_id", "full_name", "phone_number", "department",
        mode="before",
    )
    @classmethod
    def empty_string_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

# --- Dependencies ---
async def get_repo(
    settings: HrSettings = Depends(get_settings),
) -> AsyncGenerator[HrRepository, None]:
    from app.infrastructure.db.postgres_hr_repository import PostgresHrRepository

    repo = PostgresHrRepository(settings.database_url)
    try:
        yield repo
    finally:
        await repo.aclose()

def get_publisher(request: Request) -> Any:
    return getattr(request.app.state, "publisher", None)

def get_list_employees_use_case(repo: HrRepository = Depends(get_repo)) -> ListEmployeesUseCase:
    return ListEmployeesUseCase(repo)

def get_get_employee_use_case(repo: HrRepository = Depends(get_repo)) -> GetEmployeeUseCase:
    return GetEmployeeUseCase(repo)

def get_update_employee_use_case(
    repo: HrRepository = Depends(get_repo),
    publisher: Any = Depends(get_publisher),
) -> UpdateEmployeeUseCase:
    profile_service = EmployeeProfileService(publisher)
    return UpdateEmployeeUseCase(repo, profile_service)

# --- Endpoints ---
@admin_router.get("/employees", response_model=EmployeeListResponse)
async def list_employees(
    department: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    use_case: ListEmployeesUseCase = Depends(get_list_employees_use_case),
) -> EmployeeListResponse:
    result = await use_case.execute(
        department=department,
        employment_status=status,
        limit=limit,
        offset=offset,
    )
    return EmployeeListResponse(
        items=[EmployeeItem(**item.__dict__) for item in result.items],
        total=result.total,
    )

@admin_router.get("/employees/{employee_id}", response_model=EmployeeItem)
async def get_employee(
    employee_id: str,
    use_case: GetEmployeeUseCase = Depends(get_get_employee_use_case),
) -> EmployeeItem:
    employee = await use_case.execute(employee_id)
    if not employee:
        raise HTTPException(status_code=404, detail="Employee not found")
    return EmployeeItem(**employee.__dict__)

@admin_router.patch("/employees/{employee_id}", response_model=EmployeeItem)
async def update_employee(
    employee_id: str,
    request: UpdateEmployeeRequest,
    use_case: UpdateEmployeeUseCase = Depends(get_update_employee_use_case),
) -> EmployeeItem:
    provided_fields = request.model_dump(exclude_unset=True).keys()
    if not provided_fields:
        raise HTTPException(status_code=422, detail="At least one field must be provided")

    try:
        updated = await use_case.execute(
            employee_id=employee_id,
            employee_code=request.employee_code,
            job_title=request.job_title,
            manager_user_id=request.manager_user_id,
            full_name=request.full_name,
            phone_number=request.phone_number,
            date_of_birth=request.date_of_birth,
            hire_date=request.hire_date,
            department=request.department,
            provided_fields=set(provided_fields),
        )
        return EmployeeItem(**updated.__dict__)
    except ValueError as exc:
        if "not found" in str(exc).lower():
            status_code = 404
        elif "duplicate employee_code" in str(exc).lower():
            status_code = 409
        else:
            status_code = 400
        raise HTTPException(status_code=status_code, detail=str(exc))
    except Exception as exc:
        logger.error("Error updating employee: %s", exc)
        raise exc
