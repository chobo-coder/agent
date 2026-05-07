"""Pipeline handlers for each workflow step."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.session import SessionManager
    from core.orchestrator import StepResult


class BaseHandler(ABC):
    """Base class for all pipeline step handlers."""

    @abstractmethod
    def execute(self, session: "SessionManager") -> "StepResult":
        """Execute this pipeline step and return results."""
        ...
