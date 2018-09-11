import requests
import logging
import datetime
from urllib.parse import quote_plus
from unicodedata import normalize

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

DOUBLE_DEAL_S = 'N050'
DOUBLE_DEAL_M = 'N051'
DOUBLE_DEAL_L = 'N052'
TAKE_3_AWAY = 'L097'
CHEESY_BREAD = 'BRCHB'
CRAZY_WEEKDAY = 'N054'
CRAZY_WEEKDAY_ELIGIBLE_CODES = [
    '30HTCTS',
    '30HTCTB',
    '30HTMRG',
]


def commonprefix(a, b):
    if a > b:
        return commonprefix(b, a)
    for i, c in enumerate(a):
        if c != b[i]:
            return a[:i]
    return a


class PizzaApi:
    def __init__(self, config):
        self.config = config

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

    def optimize_deals(self, order_list, menu, carryout=True):
        deals = menu.get_deals()

        selected_deals = []

        # See if we need any crazy weekday deals
        num_crazy_weekday_pizzas = 0
        if CRAZY_WEEKDAY in deals:
            today = datetime.date.today()
            weekday = today.strftime('%a')
            # only on weekdays
            if any([weekday.startswith(day) for day in deals[CRAZY_WEEKDAY]['Tags']['Days']]):
                num_crazy_weekday_pizzas = len([o for o in order_list
                                                if o['Code'] in CRAZY_WEEKDAY_ELIGIBLE_CODES])
                for i in range(num_crazy_weekday_pizzas):
                    selected_deals.append({
                        'Code': CRAZY_WEEKDAY,
                        'Qty': 1,
                    })

        p = self._count_pizza(order_list)
        size_counts = self._count_pizza_sizes(order_list)
        c = self._count_cheesy_bread(order_list)

        # Don't take crazy weekday pizzas into account anymore
        size_counts[1] -= num_crazy_weekday_pizzas # subtract from medium pizzas
        p -= num_crazy_weekday_pizzas

        # Do we ned any take 3 away deals? (only for carryout)
        if c > 0 and TAKE_3_AWAY in deals and carryout:
            cheesy_bread_in_deals = 0
            while cheesy_bread_in_deals < c and p >= 2:
                selected_deals.append({
                    'Code': TAKE_3_AWAY,
                    'Qty': 1
                })
                cheesy_bread_in_deals += 1
                p -= 2
                # Figure out which sizes to put into this deal...
                # Ideally, we want to use up any single pizzas:
                if len([s for s in size_counts if s == 1]) >= 2:
                    # Remove two pizzas for which we have only 1 left
                    size_counts[size_counts.index(1)] -= 1
                    size_counts[size_counts.index(1)] -= 1
                # If we have only one single pizza, we want to use that one
                # and another from the smallest 'stack'
                elif len([s for s in size_counts if s == 1]) == 1:
                    size_counts[size_counts.index(1)] -= 1
                    nonzero_size_counts = [s for s in size_counts if s > 0]
                    size_counts[size_counts.index(min(nonzero_size_counts))] -= 1
                # If we have no single pizzas, we'll start eating off the smallest stack.
                elif len([s for s in size_counts if s == 1]) == 1:
                    nonzero_size_counts = [s for s in size_counts if s > 0]
                    size_counts[size_counts.index(min(nonzero_size_counts))] -= 1
                    nonzero_size_counts = [s for s in size_counts if s > 0]
                    size_counts[size_counts.index(min(nonzero_size_counts))] -= 1

        # Finally, add double deals:
        if size_counts[0] >= 2 and DOUBLE_DEAL_S in deals:
            selected_deals.append({
                'Code': DOUBLE_DEAL_S,
                'Qty': 1,
            })
        if size_counts[1] >= 2 and DOUBLE_DEAL_M in deals:
            selected_deals.append({
                'Code': DOUBLE_DEAL_M,
                'Qty': 1,
            })
        if size_counts[2] >= 2 and DOUBLE_DEAL_L in deals:
            selected_deals.append({
                'Code': DOUBLE_DEAL_L,
                'Qty': 1,
            })

        return selected_deals

    @staticmethod
    def _count_pizza(order_list):
        return len([o for o in order_list if o['CategoryCode'] == 'Pizza'])

    @staticmethod
    def _count_pizza_sizes(order_list):
        s, m, l = 0, 0, 0

        for order in order_list:
            if order['CategoryCode'] == 'Pizza':
                if 'SizeCode' in order:
                    if order['SizeCode'] == str(SMALL):
                        s += 1
                    if order['SizeCode'] == str(STANDARD):
                        m += 1
                    if order['SizeCode'] == str(LARGE):
                        l += 1
                else:
                    if order['Code'].startswith(str(SMALL)):
                        s += 1
                    if order['Code'].startswith(str(STANDARD)):
                        m += 1
                    if order['Code'].startswith(str(LARGE)):
                        l += 1


        return [s, m, l]

    @staticmethod
    def _count_cheesy_bread(order_list):
        return len([o for o in order_list if o['Code'] == CHEESY_BREAD])

    def create_order(self, store_id, orders, menu):
        order = {
            'ServiceMethod': 'Carryout',
            'SourceOrganizationURI': self.config['sourceURI'],
            'LanguageCode': self.config['language'],
            'StoreID': store_id,
            'Products': []
        }

        for i, item in enumerate(orders):
            if item is not None:
                item['ID'] = i
                item['isNew'] = False
                order['Products'].append(item)

        data = {
            'Order': order,
        }

        validate_url = self.config['order']['validate']
        validated_order = requests.post(validate_url, json=data, headers=self._get_headers()).json()

        carryout = validated_order['Order']['ServiceMethod'] == 'Carryout'
        deals = self.optimize_deals(validated_order['Order']['Products'], menu, carryout)

        validated_order['Order']['Coupons'] = deals
        validated_order_with_deals = requests.post(validate_url, json=validated_order, headers=self._get_headers()).json()

        price_url = self.config['order']['price']

        priced_order = requests.post(price_url, json=validated_order_with_deals, headers=self._get_headers()).json()

        if len([x for x in priced_order['Order']['StatusItems'] if x['Code'] == 'PosOrderIncomplete']) > 0:
            # TODO remove deals until it parses.
            pass

        return priced_order

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

        result = requests.get(url).json();

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
