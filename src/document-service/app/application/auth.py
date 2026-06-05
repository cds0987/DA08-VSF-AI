from dataclasses import dataclass


@dataclass(frozen=True)
class CurrentUser:
    id: str
    role: str
    department: str = ""

