import sys

from companion import self_test

# Must run before any other companion import: it points user data at a throwaway directory.
SELF_TEST = self_test.prepare(sys.argv)

from companion.app.logging_setup import setup_logging  # noqa: E402
from companion.core.legacy_data import migrate_legacy_data  # noqa: E402
from companion.qt_bootstrap import bootstrap_windows_qt_dlls, report_qt_import_failure  # noqa: E402

setup_logging()
if SELF_TEST is None:
    migrate_legacy_data()
ACTIVE_DLL_DIRS = bootstrap_windows_qt_dlls()

try:
    from companion.ui.main_window import main
except ImportError as exc:
    report_qt_import_failure(exc, ACTIVE_DLL_DIRS)
    raise


if __name__ == "__main__":
    raise SystemExit(self_test.run(SELF_TEST) if SELF_TEST else main())
