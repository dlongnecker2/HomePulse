class ChargePointHomeFlex:
    name = "Juice Box"

    def __init__(self, config=None):
        self.config = config or {}

    def configured_entities(self):
        return dict(self.config.get("home_assistant_entities", {}))
