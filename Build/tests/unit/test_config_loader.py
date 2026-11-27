from order_orchestration.config import ConfigLoader


def test_config_loader_loads_business_rules():
    loader = ConfigLoader("config")
    config = loader.load_business_rules()

    assert "order_priority" in config
    assert config["order_priority"]["VOR"] == 1
    assert config["order_priority"]["REPLENISHMENT"] == 2
    assert config["order_priority"]["PUSH"] == 3