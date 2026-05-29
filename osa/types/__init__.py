"""Core data types — pure types with no behaviour beyond validation."""

from osa.types.files import File, FileCollection
from osa.types.ingester import IngesterFileRef, IngesterRecord
from osa.types.record import Record
from osa.types.schema import Field, MetadataSchema

__all__ = [
    "Field",
    "File",
    "FileCollection",
    "IngesterFileRef",
    "IngesterRecord",
    "MetadataSchema",
    "Record",
]
