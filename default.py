class Default:
    def __init__(self, config):
        self.config = config
        self.mode_selected_message = "This is the default mode. I will simply collect your orders, " \
                                     "but not do anything else."
        self.short_description = "Just collect orders, nothing else."

    def get_orders_as_string(self, collection, orders):
        return ""

    def get_confirmation_message(self, collection, orders):
        return "Uh oh - your selected mode does not support ordering. Either" \
               " select a different mode, or use the /close command instead.", "", True

    def place_order(self, collection, orders, data):
        return "Ordering is not supported", True

    def set(self, key, arg, settings):
        if key == 'store':
            return self.set_store(arg, settings)
        if key == 'service_method':
            return self.set_service_method(arg, settings)
        if key == 'address':
            return self.set_address(arg, settings)
        if key == 'name':
            return self.set_name(arg, settings)
        if key == 'phone':
            return self.set_phone(arg, settings)
        if key == 'email':
            return self.set_email(arg, settings)
        if key == 'time':
            return self.set_time(arg, settings)

    def set_store(self, query, settings):
        return "Uh oh - setting a store does not apply to your current order mode."

    def set_service_method(self, arg, settings):
        return "Uh oh - setting a service method does not apply to your current order mode."

    def set_address(self, arg, settings):
        return "Uh oh - setting an address does not apply to your current order mode."

    def set_name(self, arg, settings):
        return "Uh oh - setting a name is irrelevant with your current order mode."

    def set_phone(self, arg, settings):
        return "Uh oh - setting a phone number is irrelevant with your current order mode."

    def set_email(self, arg, settings):
        return "Uh oh - setting an email address is irrelevant with your current order mode."

    def set_time(self, arg, settings):
        return "Uh oh - setting a time is irrelevant with your current order mode."
