import config


def get_broker():
    if config.BROKER == "kite":
        from .kite import KiteBroker
        return KiteBroker()
    if config.BROKER == "yahoo":
        from .yahoo import YahooBroker
        return YahooBroker()
    from .mock import MockBroker
    return MockBroker()
