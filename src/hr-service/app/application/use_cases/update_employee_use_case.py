from __future__ import annotations
import datetime
import logging
import uuid
from typing import Any, Protocol
from app.domain.entities.dtos import EmployeeDTO
from app.domain.repositories.hr_repository import HrRepository
from app.application.services.employee_profile_service import EmployeeProfileService

logger = logging.getLogger("hr-service.update_employee")

class UpdateEmployeeUseCase:
    def __init__(self, repo: HrRepository, profile_service: EmployeeProfileService) -> None:
        self.repo = repo
        self.profile_service = profile_service

    async def execute(
        self,
        employee_id: str,
        employee_code: str | None,
        job_title: str | None,
        manager_user_id: str | None,
        provided_fields: set[str],
    ) -> EmployeeDTO:
        # 1. Get current employee
        employee = await self.repo.get_employee(employee_id)
        if not employee:
            raise ValueError("Employee not found")

        # 2. Validation
        if "manager_user_id" in provided_fields and manager_user_id:
            if manager_user_id == employee.user_id:
                raise ValueError("Employee cannot be their own manager")
            
            manager = await self.repo.get_employee_by_user_id(manager_user_id)
            if not manager:
                raise ValueError("Manager not found")

        # 3. Update
        updated = await self.repo.update_employee(
            employee_id=employee_id,
            employee_code=employee_code,
            job_title=job_title,
            manager_user_id=manager_user_id,
            provided_fields=provided_fields,
        )
        if not updated:
            raise ValueError("Update failed")

        # 4. Publish event (best-effort)
        try:
            await self.profile_service.publish_profile_updated({
                "event_id": str(uuid.uuid4()),
                "event_version": 1,
                "occurred_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "user_id": updated.user_id,
                "account_type": updated.account_type, 
                "department": updated.department,
                "employment_status": updated.employment_status,
            })
        except Exception:
            logger.warning("failed to publish profile updated event for user_id=%s (best-effort)", 
                           updated.user_id, exc_info=True)

        return updated
