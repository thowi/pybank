import io
import logging
from typing import TextIO

from .. import importer
from .. import model
from . import dkb
from . import postfinance


# TODO: Add more importers.
IMPORTERS = (
    dkb.DkbCheckingImporter,
    dkb.DkbCreditCardImporter,
    postfinance.PostFinanceCheckingImporter,
    postfinance.PostFinanceCreditCardImporter)


logger = logging.getLogger(__name__)


class AutoImporter(importer.Importer):
    """Automatically detects the importer.

    Note that not all importers support auto detection yet.
    """
    def can_import(self, file: TextIO) -> bool:
        return self._detect(file) is not None

    def import_transactions(self, file: TextIO, currency: str | None = None) \
            -> list[model.Transaction]:
        importer = self._detect(file)
        if importer is None:
            raise ValueError('No importer found for input')
        return importer.import_transactions(file=file, currency=currency)

    def _detect(self, file: io.IOBase) -> importer.Importer:
        for importer_class in IMPORTERS:
            importer = importer_class(self._debug)
            if importer.can_import(file):
                logger.info(
                        f'Auto-detected importer: {importer_class.__name__}.')
                return importer
