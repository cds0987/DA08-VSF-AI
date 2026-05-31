# TODO: Backend Dev
# Dependency injection: wire LoginUseCase, VerifyTokenUseCase
from app.application.use_cases.auth.login_use_case import LoginUseCase
from app.infrastructure.db.postgres_user_repository import PostgresUserRepository


def get_login_use_case() -> LoginUseCase:
    user_repo = PostgresUserRepository()
    return LoginUseCase(user_repo)
