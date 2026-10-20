"""The languages Pixa is translated into, besides English (see ``pixa.i18n``).

To add a language, copy ``sv.py`` to ``<code>.py`` (the two-letter ISO 639-1
code, such as ``de``), translate its ``MESSAGES``, adapt ``plural()`` to the
language's plural forms, and list the module below. ``tests/test_i18n.py``
checks that every text in the app has a translation.
"""

from pixa.locales import sv

CATALOGS = {"sv": sv}
