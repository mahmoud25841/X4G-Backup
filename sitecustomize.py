"""Python startup hook for the Railway image.

Python imports sitecustomize automatically when it is present on sys.path.
Loading the bridge here keeps the existing X4G relay source untouched while
routing its outbound TCP connections through the configured regional exits.
"""

try:
    import exit_routing  # noqa: F401
except Exception as exc:
    # Do not prevent the application from starting if regional routing is not
    # configured or a future deployment has a temporary compatibility issue.
    # The normal X4G direct path remains available in that case.
    import logging
    logging.getLogger("x4g-exit").warning("Regional exit bridge unavailable: %s", exc)
