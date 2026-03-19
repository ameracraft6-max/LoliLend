from __future__ import annotations

import sys

from lolilend.bootstrap import APP_MODE_FLAG, configure_qt_environment


def main() -> int:
    configure_qt_environment()

    if APP_MODE_FLAG in sys.argv[1:]:
        from lolilend.app_main import run_app

        return run_app(sys.argv)

    from lolilend.launcher import run_launcher

    return run_launcher(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
