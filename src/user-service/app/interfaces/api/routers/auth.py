# TODO: Backend Dev
# POST /login        → LoginUseCase
# POST /login/sso    → Microsoft OAuth flow
# GET  /me           → VerifyTokenUseCase
from fastapi import APIRouter

router = APIRouter()
