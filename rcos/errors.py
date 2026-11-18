"""Error types. main.py catches SimulationError and prints a clear message."""


class SimulationError(Exception):
    """Base class for every simulator error."""


class ConfigError(SimulationError, ValueError):
    """Bad configuration, scenario file or process definition."""


class InvalidStateTransition(SimulationError):
    """A state change the 5-state process model does not allow."""


class ResourceError(SimulationError):
    """A resource was misused (e.g. CPU given twice, freeing unowned memory)."""


class InvariantError(SimulationError):
    """--check found the simulator in an impossible state (a bug)."""
