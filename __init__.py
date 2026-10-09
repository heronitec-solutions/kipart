try:
    from .kipart_action import KiPart
    KiPart().register()
except ImportError:
    # Outside KiCad (pytest / CLI): wx/pcbnew unavailable — package still importable as KiPartClient
    pass
