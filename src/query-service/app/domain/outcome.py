from enum import Enum, auto

class Outcome(Enum):
    REFUSE = auto()
    CLARIFY = auto()
    NO_INFO = auto()
    OFF_TOPIC = auto()
    SUCCESS = auto()
    ERROR = auto()


class AgentState(Enum):
    """Trạng thái của ReAct Agent Loop"""
    IDLE = auto()
    THINKING = auto()
    ACTING = auto()
    OBSERVING = auto()
    GENERATING = auto()
    DONE = auto()
    ERROR = auto()
    FALLBACK = auto()
