from enum import Enum, auto


class AutomationState(Enum):
    IDLE                  = auto()
    WAITING_FOR_TITLE     = auto()
    NAVIGATING_TO_TARGET  = auto()
    WAITING_FOR_BATTLE    = auto()
    CHECKING_FOR_SHINY    = auto()
    SHINY_FOUND           = auto()
    SOFT_RESETTING        = auto()
    WAITING_FOR_RESET     = auto()
    STOPPED               = auto()
    ERROR                 = auto()


class StateMachine:
    """Minimal state machine used to track automation progress."""

    def __init__(self, initial: AutomationState = AutomationState.IDLE):
        self.state = initial

    def transition(self, new_state: AutomationState):
        self.state = new_state

    def is_in(self, state: AutomationState) -> bool:
        return self.state == state

    def __repr__(self):
        return f"StateMachine(state={self.state.name})"
