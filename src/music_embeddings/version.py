"""Single source of truth for SynthDigger's version numbers.

Two independent numbers are tracked here:

* ``APP_VERSION`` - the released version of the SynthDigger software. ``pyproject.toml``
  reads this attribute (``[tool.setuptools.dynamic]``) so the packaged version and
  the runtime value can never drift. Surfaced by ``synthdigger version``, ``synthdigger
  --version``, and the cloud app's ``/api/music/version`` endpoint / footer.

* ``SCHEMA_VERSION`` - the version of the local DuckDB catalog layout. Bump this
  (and add a CHANGELOG entry with upgrade steps) whenever a release needs an
  existing catalog to be rebuilt or migrated. The value stamped into a catalog at
  creation time is compared against this so ``synthdigger version`` can tell the user
  whether upgrade steps are required. v1 is the original layout (four ``embedding``
  tables); catalogs created before versioning existed are treated as v1.

Keep this module import-light: setuptools parses ``APP_VERSION`` from the source
without importing the package, so it must remain a plain literal assignment.
"""

APP_VERSION = "1.0.3"
SCHEMA_VERSION = 1
