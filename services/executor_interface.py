class BaseExecutor:
    def run(self, ticket: dict, plan: dict, options: dict):
        raise NotImplementedError("Executor must implement run()")
    
from abc import ABC, abstractmethod


class ExecutorInterface(ABC):

    @abstractmethod
    def run(self, ticket: dict, plan: dict, options: dict, context: dict):
        pass

    @abstractmethod
    def get_status(self, execution_id: str):
        pass

    @abstractmethod
    def get_logs(self, execution_id: str):
        pass    