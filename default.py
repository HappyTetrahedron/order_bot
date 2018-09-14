class Default:
    def __init__(self, config):
        self.config = config
        self.mode_selected_message = "This is the default mode. I will simply collect your orders, " \
                                     "but not do anything else."
        self.short_description = "Just collect orders, nothing else."

    def get_orders_as_string(self, collection, orders):
        return ""

    def set_store(self, query, settings):
        return "Uh oh - setting a store does not apply to your current order mode."
