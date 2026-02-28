# services/executor_factory.py

from .rundeck_executor import RundeckExecutor
from .awx_executor import AWXExecutor


def get_executor(executor_type: str):

    if executor_type == "rundeck":
        return RundeckExecutor()

    if executor_type == "awx":
        return AWXExecutor()

    raise ValueError(f"Unsupported executor: {executor_type}")