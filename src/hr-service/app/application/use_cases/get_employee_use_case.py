from __future__ import annotations
from app.domain.entities.dtos import EmployeeDTO
from app.domain.repositories.hr_repository import HrRepository

class GetEmployeeUseCase:
    def __init__(self, repo: HrRepository) -> None:
        self.repo = repo

    async def execute(self, employee_id: str) -> EmployeeDTO | None:
        return await self.repo.get_employee(employee_id)
