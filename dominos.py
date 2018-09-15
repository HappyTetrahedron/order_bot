import time

import requests
import logging
import datetime
import json
import re
from urllib.parse import quote_plus
from unicodedata import normalize
from default import Default

logger = logging.getLogger(__name__)

synonyms_standard = [
    'standard',
    'normal',
    'regular',
    'medium',
    'm',
    '30cm',
]
synonyms_small = [
    'small',
    's',
    '25cm',
]
synonyms_large = [
    'large',
    'big',
    'l',
    'xl',
    '35cm',
]

STANDARD, SMALL, LARGE = 30, 25, 35
PIZZA_CODE_PREFIX = 'HT'  # H = standard crust. Dunno what the T stands for but it's the only option.

DEALS = [
    'N044',  # Crazy Tuesday
    'N054',  # Crazy Weekday
    'L097',  # Take 3 Away
    'N050',  # Double Deal S
    'N051',  # Double Deal M
    'N052',  # Double Deal L
]


def commonprefix(a, b):
    if a > b:
        return commonprefix(b, a)
    for i, c in enumerate(a):
        if c != b[i]:
            return a[:i]
    return a


def capitalize(s):
    return " ".join(w.capitalize() for w in s.split())


class Dominos(Default):
    def __init__(self, config):
        Default.__init__(self, config)
        self.mode_selected_message = "You're using Domino's Pizza Mode. I will try to interpret your orders " \
                                     "as Domino's Pizza Menu Items, and when you submit it, I will order at " \
                                     "your configured Domino's Pizza Store."
        self.short_description = "Order at Domino's Pizza stores in Switzerland"

    def get_stores_near(self, query):
        lat, lng = self._get_coordinates(query)

        url = self.config['store']['find'].format(
            regioncode=quote_plus(self.config['regionCode']),
            lat=str(lat),
            lng=str(lng),
        )

        response = requests.get(url, headers=self._get_headers(add_response_type=True)).json()
        return response['Stores']

    def get_closest_store(self, query):
        stores = self.get_stores_near(query)
        if len(stores) == 0:
            return None
        return stores[0]

    def get_store_info(self, store_id):
        url = self.config['store']['info'].format(
            storeID=store_id
        )
        return requests.get(url, headers=self._get_headers(add_response_type=True)).json()

    def get_menu_from_store(self, store_id):
        url = self.config['store']['menu'].format(
            storeID=store_id,
            lang=self.config['language']
        )
        response = requests.get(url).json()
        return Menu(response)

    def parse_all_orders(self, order, menu):
        orders = order.split(';')
        return [self._parse_order(part.strip(), menu) for part in orders]

    def optimize_deals(self, order_list, menu, store_id, service_method='Carryout'):
        deals = menu.get_deals()

        ordered_item_codes = [i['Code'] for i in order_list]

        selected_deals = []

        for deal_id in DEALS:
            # Is the deal available right now?
            if deal_id not in deals:
                continue
            # Is the deal available on this day of the week?
            if 'Tags' in deals[deal_id] and 'Days' in deals[deal_id]['Tags']:
                today = datetime.date.today()
                weekday = today.strftime('%a')
                available_days = deals[deal_id]['Tags']['Days']
                if not (
                    isinstance(available_days, str) and weekday.startswith(available_days)
                    or any([weekday.startswith(day) for day in available_days])
                ):
                    continue
            # Is the deal available for this service method?
            if service_method != deals[deal_id]['Tags']['ValidServiceMethods'] \
                    and service_method not in deals[deal_id]['Tags']['ValidServiceMethods']:
                continue

            deal_url = self.config['store']['deals'].format(
                storeID=store_id,
                lang=self.config['language'],
                dealID=deal_id
            )

            deal_info = requests.get(deal_url, headers=self._get_headers()).json()

            deal_complete = True
            while deal_complete:
                items_selected = []
                for slot in deal_info['ProductGroups']:
                    for i in range(slot['RequiredQty']):
                        eligible = slot['ProductCodes']
                        items_possible = [item in eligible for item in ordered_item_codes]
                        if any(items_possible):
                            selected_item = ordered_item_codes[items_possible.index(True)]
                            items_selected.append(selected_item)
                            ordered_item_codes.remove(selected_item)
                        else:
                            deal_complete = False
                            break
                if not deal_complete:
                    # Could not complete deal: make items available again for other deals
                    for item in items_selected:
                        ordered_item_codes.append(item)
                else:
                    selected_deals.append({
                        'Code': deal_id,
                        'Qty': 1,
                    })

        return selected_deals

    def create_order(self, orders, menu, settings):
        store_id = settings['store_id'] if 'store_id' in settings else 'wat'
        service_method = settings['service_method'] if 'service_method' in settings else 'Delivery'
        order = {
            'ServiceMethod': service_method,
            'SourceOrganizationURI': self.config['sourceURI'],
            'LanguageCode': self.config['language'],
            'StoreID': store_id,
            'Products': []
        }

        if 'address' in settings:
            order['Address'] = {
                'City': settings['address']['city'],
                'PostalCode': settings['address']['zip'],
                'StreetName': settings['address']['street'],
                'StreetNumber': settings['address']['street_no'],
                'Coordinates': {
                    'Latitude': settings['address']['coords']['lat'],
                    'Longitude': settings['address']['coords']['lng'],
                },
            }

        if 'first_name' in settings:
            order['FirstName'] = settings['first_name']

        if 'last_name' in settings:
            order['LastName'] = settings['last_name']

        if 'email' in settings:
            order['Email'] = settings['email']

        if 'phone' in settings:
            order['Phone'] = settings['phone']

        if 'phone_prefix' in settings:
            order['PhonePrefix'] = settings['phone']

        if 'time' in settings:
            today = datetime.date.today()
            date = today.strftime('%Y-%m-%d ')
            order['FutureOrderTime'] = date + settings['time'] + ":00"

        for i, item in enumerate(orders):
            if item is not None:
                item['ID'] = i
                item['isNew'] = False
                order['Products'].append(item)

        data = {
            'Order': order,
        }

        validate_url = self.config['order']['validate']
        encoded = json.dumps(data, ensure_ascii=False).encode('cp1252')
        validated_order = requests.post(validate_url, data=encoded, headers=self._get_headers()).json()

        deals = self.optimize_deals(
            validated_order['Order']['Products'],
            menu,
            validated_order['Order']['StoreID'],
            validated_order['Order']['ServiceMethod'],
        )

        validated_order['Order']['Coupons'] = deals
        encoded = json.dumps(validated_order, ensure_ascii=False).encode('cp1252')
        validated_order_with_deals = requests.post(validate_url, data=encoded, headers=self._get_headers()).json()

        price_url = self.config['order']['price']

        encoded = json.dumps(validated_order_with_deals, ensure_ascii=False).encode('cp1252')
        priced_order = requests.post(price_url, data=encoded, headers=self._get_headers()).json()

        if self.config['debug']:
            import pprint
            pprint.pprint(priced_order)

        return priced_order

    def get_orders_as_string(self, collection, orders):
        text = "=== Domino's Pizza Order ===\n"
        if not ('settings' in collection and 'store_id' in collection['settings']):
            text += "You have not configured a Domino's Pizza store. Please do so using the /store command."
            return text

        validated_orders, menu = self.order_list_to_validated(collection, orders)

        text += self._orders_to_text(validated_orders, menu)

        return text.strip()

    def get_confirmation_message(self, collection, orders):
        text = ""
        if not ('settings' in collection and 'store_id' in collection['settings']):
            text += "You have not configured a Domino's Pizza store. Please do so using the /store command."
            return text, "", True

        validated_orders, menu = self.order_list_to_validated(collection, orders)

        if validated_orders['Status'] != 0:
            text += "There are some issues with your order:\n"
            text += self.extract_error_message(validated_orders)
            text += "Please fix them first and then try again."
            return text, "", True

        text += "You wish to order the following:\n"
        text += self._orders_to_text(validated_orders, menu)

        store_info = self.get_store_info(collection['settings']['store_id'])

        text += "\n\nYou will order at the {} store at {} in {}\n".format(
            store_info['StoreName'].strip(),
            store_info['StreetName'].strip(),
            store_info['City'].strip(),
        )

        settings = collection['settings']

        service_method = settings['service_method'] if 'service_method' in settings else 'Delivery'

        if 'first_name' in settings:
            text += "Name: {} {}\n".format(settings['first_name'], settings['last_name'])

        if 'email' in settings:
            text += "E-mail: {}\n".format(settings['email'])

        if 'phone' in settings:
            text += "Phone: +{} 0{}\n".format(settings['phone_prefix'], settings['phone'])

        if 'time' in settings:
            today = datetime.date.today()
            date = today.strftime('%Y-%m-%d ')
            text += "Order time: {}\n".format(date + settings['time'])

        if 'first_name' in settings:
            text += "Name: {} {}\n".format(settings['first_name'], settings['last_name'])

        text += 'Service method: {}\n'.format(service_method)

        if service_method == 'Delivery' and 'address' in settings:
            text += "Delivery address: {} {}, {} {}\n".format(
                settings['address']['street'],
                settings['address']['street_no'],
                settings['address']['zip'],
                settings['address']['city'],
            )
            text += "http://www.google.com/maps/place/{},{}".format(
                settings['address']['coords']['lat'],
                settings['address']['coords']['lng'],
            )

        return text, validated_orders, False

    def place_order(self, collection, orders, data):
        return "Blerp", False

    @staticmethod
    def extract_error_message(order):
        message = ""

        def format_status_item(status_item):
            if 'PulseText' in item:
                return "{}: {}\n".format(
                    item['Code'],
                    item['PulseText']
                )
            if 'Message' in item:
                return "{}: {}\n".format(
                    item['Code'],
                    item['Message']
                )
            else:
                return "{}\n".format(item['Code'])

        if order['Status'] != 0:
            if 'StatusItems' in order['Order']:
                for item in order['Order']['StatusItems']:
                    message += format_status_item(item)

        for item in order['Order']['Products']:
            if item['Status'] != 0:
                if 'StatusItems' in item:
                    message += "Errors with {}:\n".format(item['Name'] if 'Name' in item else item['Code'])
                    for status in item['StatusItems']:
                        message += format_status_item(status)

        for item in order['Order']['Coupons']:
            if item['Status'] != 0:
                if 'StatusItems' in item:
                    message += "Errors with deal {}:\n".format(item['Code'])
                    for status in item['StatusItems']:
                        message += format_status_item(status)

        return message

    def order_list_to_validated(self, collection, orders):
        order_string = ""
        for order in orders:
            order_string += "{};".format(order['order_text'].split('\n')[0])
        if order_string.endswith(";"):
            order_string = order_string[:-1]

        menu = self.get_menu_from_store(collection['settings']['store_id'])

        orders = self.parse_all_orders(order_string, menu)
        validated = self.create_order(orders, menu, collection['settings'])
        return validated, menu

    def set_store(self, query, settings):
        if len(query) <= 0:
            return "You need to provide an argument for this command. Which store do you " + \
                                      "want to use? (Provide a location)"
        store = self.get_closest_store(query)

        if store is None:
            return "Uh oh, I couldn't find a Domino's store at that location. Try another."

        settings['store_id'] = store['StoreID']
        return "You will now order at the {} store ({}, {} {})".format(
            store['StoreName'],
            store['StreetName'],
            store['PostalCode'],
            store['City']
        )

    def set_service_method(self, arg, settings):
        if arg == 'carryout' or arg == 'pickup' or arg == 'carry-out':
            settings['service_method'] = 'Carryout'
            return "We set your service method to Carry-out."
        elif arg == 'delivery':
            settings['service_method'] = 'Delivery'
            return "We set your service method to Delivery."
        else:
            return "I didn't understand that - pick either Carryout or Delivery."

    def set_address(self, arg, settings):
        regex = '(.+)\s+(\S+),\s+(\d{4,5})\s+([^,]+)'

        matches = re.match(regex, arg)

        if not matches:
            return "Sorry, I could not understand this address. Please use the following format:\n" \
                   "<street> <number>, <zip> <city>"

        address = {
            'street': capitalize(matches.group(1)),
            'street_no': capitalize(matches.group(2)),
            'zip': capitalize(matches.group(3)),
            'city': capitalize(matches.group(4))
        }

        try:
            lat, lng = self._get_coordinates(arg)
        except ValueError:
            return "Sorry, I could not find this address. Did you misspell it?"

        address['coords'] = {
            'lat': lat,
            'lng': lng,
        }

        settings['address'] = address
        return "I set your delivery address to {} {} in {} {}".format(
            address['street'],
            address['street_no'],
            address['zip'],
            address['city'],
        )

    def set_time(self, arg, settings):
        try:
            t = time.strptime(arg, "%H:%M")
        except ValueError:
            return "Sorry, I didn't understand that. Please specify a time in the 24-hour format, hh:mm"

        settings['time'] = arg
        return "I set your order time to {} (on the same day as you place your order)".format(
            time.strftime("%H:%M", t)
        )

    def set_name(self, name, settings):
        regex = '(.+)\s+(\S+)'

        matches = re.match(regex, name)

        if not matches:
            return "Sorry, I could not understand this name. Please use the following format:\n" \
                   "<firstname> <lastname>"

        settings['first_name'] = capitalize(matches.group(1))
        settings['last_name'] = capitalize(matches.group(2))

        return "I set your name to {} {}.".format(settings['first_name'], settings['last_name'])

    def set_phone(self, phone, settings):
        regex = '^\+?0*([1-9]+)[0\s]+([\d\s]{9,18})$'

        matches = re.match(regex, phone)

        if not matches:
            return "Please enter a valid phone number (with country code).\n" \
                   "Example: +41 079 123 45 67"

        settings['phone_prefix'] = matches.group(1)
        settings['phone'] = matches.group(2).replace(' ', '')
        return "I set your phone number to +{} 0{}".format(settings['phone_prefix'], settings['phone'])

    def set_email(self, email, settings):
        regex = '^(\S+)@(\S+)\.([a-z]+)$'

        matches = re.match(regex, email)

        if not matches:
            return "Please enter a valid email address."

        settings['email'] = email
        return "I set your email address to {}".format(email)

    @staticmethod
    def get_customization_string(validated_order, menu):
        if 'Options' not in validated_order:
            return ""

        string = ""
        for k, v in validated_order['Options'].items():
            if v == 0:
                string += 'no '
            if '1/1' in v and v['1/1'] == "1.5":
                string += 'extra '
            if '1/1' in v and v['1/1'] == "0.0":
                string += 'no '
            string += menu.get_toppings()[k]['Name']
            string += ', '

        if string.endswith(', '):
            string = string[:-2]
        return string

    def _parse_order(self, order, menu):
        # Step 1: Which product are we ordering?
        products = menu.get_products()
        matching_products = self._find_matches(order, products)
        if len(matching_products) == 0:
            return None
        best_product = matching_products[0]['product']

        dominos_order = {
            'Code': best_product['Variants'][0],
            'Qty': 1,
            'Options': self._get_default_toppings(best_product),
        }

        # Step 2: Which size? (currently only for pizza)
        if best_product['ProductType'].lower() == 'pizza':
            size = STANDARD
            for word in order.replace(',', '').split(' '):
                if word.strip() in synonyms_small:
                    size = SMALL
                if word.strip() in synonyms_large:
                    size = LARGE

            code_prefix = str(size) + PIZZA_CODE_PREFIX
            for code in best_product['Variants']:
                if code.startswith(code_prefix):
                    dominos_order['Code'] = code

            # Step 3: For pizza: which toppings?
            toppings = {k: v for k, v in menu.get_toppings().items()
                        if 'Sauce' not in v['Tags'] or not v['Tags']['Sauce']}
            matching_toppings = self._find_matches(order, toppings)
            for match in matching_toppings:
                quantity = 1
                if match['word'] > 0:
                    word_before = order.split(',')[match['part']].strip().split(' ')[match['word'] - 1].lower()
                    if word_before == 'no':
                        quantity = 0
                    if word_before == 'extra':
                        quantity = 1.5
                if quantity > 0:
                    dominos_order['Options'][match['product']['Code']] = {
                        '1/1': str(quantity)
                    }
                else:
                    dominos_order['Options'][match['product']['Code']] = 0
        return dominos_order

    def _orders_to_text(self, validated_orders, dominos_menu):
        text = ""
        currency = validated_orders['Order']['Currency']

        for item in validated_orders['Order']['Coupons']:
            text += "- {}\n".format(dominos_menu.get_deals()[item['Code']]['Name'].split('-')[0])

        for item in validated_orders['Order']['Products']:
            if 'AutoRemove' in item and item['AutoRemove']:
                continue
            text += "*{}* {} {}".format(
                item['Name'] if 'Name' in item else item['Code'],
                item['Price'] if 'Price' in item else "--",
                currency
            )
            if 'Options' in item:
                text += " - "
                text += self.get_customization_string(item, dominos_menu)
            text += '\n'
            if 'StatusItems' in item:
                for status_item in item['StatusItems']:
                    text += status_item['Code']
                    text += " "
                text += '\n'

        if 'Amounts' in validated_orders['Order']:
            text += "*Total*: {} {}\n".format(validated_orders['Order']['Amounts']['Customer'], currency)
        if 'StatusItems' in validated_orders['Order']:
            text += '\nDominos reports the following issues with your order:\n'
            for status_item in validated_orders['Order']['StatusItems']:
                text += status_item['Code']
                text += " "
            text += '\n'
            logger.warning(validated_orders['Order']['StatusItems'])

        return text.strip()

    @staticmethod
    def _get_default_toppings(product):
        options = {}
        if product['DefaultToppings']:
            for topping in product['DefaultToppings'].split(','):
                values = topping.split('=')
                options[values[0]] = {
                    '1/1': values[1]
                }
        return options

    @staticmethod
    def _find_matches(order, products, min_words=2, min_chars_first_word=3, min_chars_total=5):
        matches_found = []
        order_parts = normalize('NFD', order).encode('ascii', 'ignore').decode('ascii').split(',')
        for part_index, part in enumerate(order_parts):
            order_words = part.strip().lower().split(' ')
            for p in products.values():
                name_words = normalize('NFD', p['Name'].lower()).encode('ascii', 'ignore').decode('ascii').split(' ')
                for o, order_word in enumerate(order_words):
                    for n, name_word in enumerate(name_words):
                        match = len(commonprefix(order_word, name_word))
                        # Heuristic. Start scan from X matching characters onward.
                        if match >= min(min_chars_first_word, len(name_word)):
                            matches = []
                            for nn, next_name_word in enumerate(name_words[n:]):
                                if o+nn < len(order_words):
                                    match = len(commonprefix(next_name_word, order_words[o+nn]))
                                    if match > 0:
                                        matches.append(match)
                            # Heuristic. If the product has multiple words, at least X must match.
                            if len(matches) >= min(min_words, len(name_words)):
                                # Heuristic. In total, at least X characters must match (if the product has that many).
                                if sum(matches) >= min(sum([len(w) for w in name_words]), min_chars_total):
                                    matches_found.append({
                                        'len': len(matches),
                                        'sum': sum(matches),
                                        'part': part_index,
                                        'word': o,
                                        'product': p,
                                    })
        matches_found.sort(key=lambda m: (m['len'], m['sum']), reverse=True)
        return matches_found

    def _get_coordinates(self, query):
        url = self.config['geocode']['url'].format(
            query=quote_plus(query),
            key=self.config['geocode']['key']
        )

        result = requests.get(url).json()

        import pprint
        pprint.pprint(result)

        if len(result['results'][0]['locations']) <= 0:
            raise ValueError('no such location')

        else:
            return result['results'][0]['locations'][0]['latLng']['lat'], \
                   result['results'][0]['locations'][0]['latLng']['lng']

    def _get_headers(self, add_response_type=False):
        headers = {
            "DPZ-Language": self.config['language'],
            "DPZ-Market": self.config['market'],
            "Accept": "application/json",
        }
        if add_response_type:
            headers["Accept"] = self.config['store']['responseType']
        return headers


class Menu:
    def __init__(self, json):
        self.json = json

    def get_products(self):
        return self.json['Products']

    def get_toppings(self):
        return self.json['Toppings']['Pizza']

    def get_deals(self):
        return self.json['Coupons']
