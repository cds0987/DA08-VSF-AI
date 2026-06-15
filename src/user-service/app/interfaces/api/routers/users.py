from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from app.application.exceptions import ConflictError, NotFoundError, PermissionDeniedError
from app.application.use_cases.users.create_user_use_case import CreateUserUseCase
from app.application.use_cases.users.list_users_use_case import ListUsersUseCase
from app.application.use_cases.users.set_user_active_use_case import SetUserActiveUseCase
from app.domain.entities.user import User
from app.interfaces.api.dependencies import (
    get_create_user_use_case,
    get_list_users_use_case,
    get_set_user_active_use_case,
    require_admin,
)
from app.interfaces.api.schemas.user import (
    CreateUserRequest,
    UserActiveResponse,
    UserItem,
    UserList,
)


router = APIRouter(prefix="/users", tags=["users"])


@router.post("", status_code=201, response_model=UserItem)
async def create_user(
    request: CreateUserRequest,
    actor: User = Depends(require_admin),
    use_case: CreateUserUseCase = Depends(get_create_user_use_case),
) -> UserItem:
    try:
        user = await use_case.execute(
            actor=actor,
            email=request.email,
            password=request.password,
            role=request.role,
            account_type=request.account_type,
            department=request.department,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only",
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return UserItem(
        id=user.id,
        email=user.email,
        role=_role_value(user.role),
        account_type=user.account_type,
        is_active=user.is_active,
    )


@router.get("", response_model=UserList)
async def list_users(
    is_active: bool | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    actor: User = Depends(require_admin),
    use_case: ListUsersUseCase = Depends(get_list_users_use_case),
) -> UserList:
    try:
        result = await use_case.execute(
            actor=actor,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only",
        ) from exc

    return UserList(
        items=[
            UserItem(
                id=user.id,
                email=user.email,
                role=_role_value(user.role),
                account_type=user.account_type,
                is_active=user.is_active,
            )
            for user in result.items
        ],
        total=result.total,
    )


@router.patch("/{user_id}/deactivate", response_model=UserActiveResponse)
async def deactivate_user(
    user_id: str,
    request: Request,
    actor: User = Depends(require_admin),
    use_case: SetUserActiveUseCase = Depends(get_set_user_active_use_case),
) -> UserActiveResponse:
    return await _set_active(user_id, False, request, actor, use_case)


@router.patch("/{user_id}/reactivate", response_model=UserActiveResponse)
async def reactivate_user(
    user_id: str,
    request: Request,
    actor: User = Depends(require_admin),
    use_case: SetUserActiveUseCase = Depends(get_set_user_active_use_case),
) -> UserActiveResponse:
    return await _set_active(user_id, True, request, actor, use_case)


async def _set_active(
    user_id: str,
    is_active: bool,
    request: Request,
    actor: User,
    use_case: SetUserActiveUseCase,
) -> UserActiveResponse:
    try:
        result = await use_case.execute(
            actor=actor,
            user_id=user_id,
            is_active=is_active,
            ip_address=request.client.host if request.client else None,
        )
    except PermissionDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin only",
        ) from exc
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        ) from exc
    return UserActiveResponse(id=result.id, is_active=result.is_active)


def _role_value(role: object) -> str:
    value = getattr(role, "value", None)
    return str(value if value is not None else role)

