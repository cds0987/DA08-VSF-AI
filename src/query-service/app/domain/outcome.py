from enum import Enum, auto

class Outcome(Enum):
    REFUSE = auto()
    CLARIFY = auto()
    NO_INFO = auto()
    OFF_TOPIC = auto()
    SUCCESS = auto()
