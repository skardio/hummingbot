from enum import Enum


class RunnableStatus(Enum):
    NOT_STARTED = 1
    RUNNING = 2
    SHUTTING_DOWN = 3
    TERMINATED = 4
    CLOSING = 5  # Phase 3: Added at END to avoid breaking existing int comparisons
