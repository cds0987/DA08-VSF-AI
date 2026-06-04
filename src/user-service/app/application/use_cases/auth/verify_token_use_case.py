from app.application.exceptions import InactiveUserError, InvalidTokenError
from app.application.security import TokenService
from app.domain.entities.user import User
from app.domain.repositories.user_repository import UserRepository


class VerifyTokenUseCase:
    def __init__(
        self,
        user_repository: UserRepository,
        token_service: TokenService,
    ) -> None:
        self.user_repository = user_repository
        self.token_service = token_service

    async def execute(self, token: str) -> User:
        try:
            payload = self.token_service.decode_access_token(token)
        except Exception as exc:
            raise InvalidTokenError() from exc

        subject = payload.get("sub")
        jti = payload.get("jti")
        if not subject or not jti:
            raise InvalidTokenError()

        user = await self.user_repository.get_by_id(str(subject))
        if user is None:
            raise InvalidTokenError()
        if not user.is_active:
            raise InactiveUserError()
        return user

