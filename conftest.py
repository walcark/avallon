"""Give the test session a notes directory before Django reads the settings.

``settings.CONTENT_DIR`` is resolved at import time and now raises when nothing
is configured, which is the right behaviour for a user and the wrong one for a
test run on a machine (or in CI) that has no notes repository. A throwaway
directory here means the tests never depend on the developer's own setup; each
test then rebinds it to its own tree through the `notes` fixture.
"""

import os
import tempfile

os.environ.setdefault("AVALLON_CONTENT_DIR", tempfile.mkdtemp(prefix="avallon-tests-"))
