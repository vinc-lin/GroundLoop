"""Enable ``python -m groundloop.cli`` to run the CLI.

The ``gloop`` console script points at ``groundloop.cli:main``; this shim makes the
package directly executable too (used by the Type-2 live e2e tests, which invoke
``python -m groundloop.cli produce/index ...`` in a subprocess).
"""
from groundloop.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
