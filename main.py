from companion.app.logging_setup import setup_logging
from companion.core.legacy_data import migrate_legacy_data
from companion.qt_bootstrap import bootstrap_windows_qt_dlls, report_qt_import_failure

setup_logging()
migrate_legacy_data()
ACTIVE_DLL_DIRS = bootstrap_windows_qt_dlls()

try:
    from companion.ui.main_window import main
except ImportError as exc:
    report_qt_import_failure(exc, ACTIVE_DLL_DIRS)
    raise


if __name__ == "__main__":
    raise SystemExit(main())
