from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: str
    account_type: str
    department: str = ""

