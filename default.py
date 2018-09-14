class Default:
    def __init__(self, config):
        self.config = config
        self.mode_selected_message = "This is the default mode. I will simply collect your orders, " \
                                     "but not do anything else."
        self.short_description = "Just collect orders, nothing else."

    def get_orders_as_string(self, collection, orders):
        return ""

    def set(self, key, arg, settings):
        if key == 'store':
            return self.set_store(arg, settings)
        if key == 'service_method':
            return self.set_service_method(arg, settings)
        if key == 'address':
            return self.set_address(arg, settings)

    def set_store(self, query, settings):
        return "Uh oh - setting a store does not apply to your current order mode."

    def set_service_method(self, arg, settings):
        return "Uh oh - setting a service method does not apply to your current order mode."

    def set_address(self, arg, settings):
        return "Uh oh - setting an address does not apply to your current order mode."
