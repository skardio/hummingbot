from typing import Optional, TypeVar

from pydantic import BaseModel

from hummingbot.strategy_v2.executors.data_types import ExecutorConfigBase
from hummingbot.strategy_v2.models.executors import EarlyStopReason

ExecutorConfigType = TypeVar("ExecutorConfigType", bound=ExecutorConfigBase)


class ExecutorAction(BaseModel):
    """
    Base class for bot actions.
    """
    controller_id: Optional[str] = "main"


class CreateExecutorAction(ExecutorAction):
    """
    Action to create an executor.
    """
    executor_config: ExecutorConfigType


class StopExecutorAction(ExecutorAction):
    """
    Action to stop an executor.
    US-006: Added early_stop_reason for detailed tracking.
    """
    executor_id: str
    keep_position: Optional[bool] = False
    early_stop_reason: Optional[EarlyStopReason] = None  # US-006: Reason for early stop


class StoreExecutorAction(ExecutorAction):
    """
    Action to store an executor.
    """
    executor_id: str
