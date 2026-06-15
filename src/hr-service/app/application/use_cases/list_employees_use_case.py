from __future__ import annotations
from dataclasses import dataclass
from app.domain.entities.dtos import EmployeeDTO
from app.domain.repositories.hr_repository import HrRepository

@dataclass(frozen=True)
class EmployeeListResult:
    items: list[EmployeeDTO]
    total: int

class ListEmployeesUseCase:
    def __init__(self, repo: HrRepository) -> None:
        self.repo = repo

    async def execute(
        self,
        department: str | None = None,
        employment_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> EmployeeListResult:
        items, total = await self.repo.list_employees(
            department=department,
            employment_status=employment_status,
            limit=limit,
            offset=offset,
        )
        return EmployeeListResult(items=items, total=total)
