"""Documentation about fs_irods."""
import logging
from .iRODSFS import iRODSFS
from .utils import can_create

logging.getLogger(__name__).addHandler(logging.NullHandler())

__author__ = "Helge Hecht"
__email__ = "helge.hecht@recetox.muni.cz"
__version__ = "0.3.1"

__all__ = ["iRODSFS", "can_create"]
