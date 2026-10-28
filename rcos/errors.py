"""Exception types.  Every failure the simulator can detect raises one of these,
so main.py can report a clear message instead of a raw traceback."""


class SimulationError(Exception):
    """Base class for all simulator errors."""


class ConfigError(SimulationError, ValueError):
    """Bad configuration, scenario file, or process definition."""


class InvalidStateTransition(SimulationError):
    """A process tried to make a transition the 5-state model does not allow."""


class ResourceError(SimulationError):
    """A resource-manager contract was violated (e.g. CPU double-assigned,
    freeing memory that was never allocated, unknown I/O device)."""
