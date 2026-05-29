"""OSA Python SDK — hooks and conventions for the Open Scientific Archive."""

from osa.authoring.convention import convention
from osa.authoring.hook import hook
from osa.authoring.ingester import Ingester
from osa.authoring.validator import Reject
from osa.runtime.ingester_context import IngesterContext
from osa.types.ingester import (
    IngesterFileRef,
    IngesterRecord,
    IngesterSchedule,
    InitialRun,
    Limits,
)
from osa.types.record import Record
from osa.types.schema import Field, MetadataSchema

# Schema is a user-friendly alias for MetadataSchema
Schema = MetadataSchema

__all__ = [
    "Field",
    "Ingester",
    "IngesterContext",
    "IngesterFileRef",
    "IngesterRecord",
    "IngesterSchedule",
    "InitialRun",
    "Limits",
    "MetadataSchema",
    "Record",
    "Reject",
    "Schema",
    "convention",
    "hook",
]
