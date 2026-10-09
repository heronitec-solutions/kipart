try:
    from .kipart_action import KiPart
    KiPart().register()
except ImportError:
    import sys
    # Outside KiCad, wx/pcbnew are missing and this package must stay importable
    # for pytest. Inside KiCad those modules are already loaded, so a failed
    # import means the PCM zip is incomplete and the plugin must not vanish.
    if "pcbnew" in sys.modules:
        raise
