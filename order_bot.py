#!/usr/bin/env python
# -*- coding: utf-8 -*-
import random
import yaml
import logging
import dataset
import re
import json

from uuid import uuid4
from telegram.ext import Updater, CommandHandler
from mentions_handler import MentionsHandler
from pizza_api import PizzaApi

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)


AFFIRMATIONS = [
    "Cool",
    "Nice",
    "Awesome",
    "Neat",
    "Whoo",
    "Wonderful",
    "Splendid",
]


class PollBot:
    def __init__(self):
        self.db = None
        self.config = None
        self.pizza = None

    def start(self, bot, update):
        """Send a message when the command /start is issued."""
        table = self.db['order_collections']
        defaults = self.db['defaults']
        default_settings = defaults.find_one(chat=update.message.chat.id)

        new_collection = {
            'chat': update.message.chat.id,
            'uuid': str(uuid4()),
            'active': True,
            'settings': {}
        }

        if default_settings:
            new_collection['settings'] = self.deserialize(default_settings)['settings']

        msg = update.message.reply_text('{}! I will now start collecting your orders! '
                                        'Send a message that @mentions me and I '
                                        'will add it to the list.'.format(self.get_affirmation()),
                                        quote=False)

        new_collection['message'] = msg.message_id
        table.upsert(self.serialize(new_collection), ['chat'])

    def mention(self, bot, update):
        collections = self.db['order_collections']
        collection = collections.find_one(chat=update.message.chat.id)

        order_text = update.message.text.replace("@{}".format(self.config['bot_name']), "")
        if len(order_text) > 400:
            order_text = order_text[:400] + "..."
        order_text = re.sub(r'\n\s*', "\n", order_text)
        order_text.strip()
        if collection is not None:
            orders = self.db['orders']
            new_order = {
                'collection_uuid': collection['uuid'],
                'chat': update.message.chat.id,
                'user_id': update.message.from_user.id,
                'user_name': update.message.from_user.first_name,
                'order_text': order_text,
            }
            orders.upsert(new_order, ['chat', 'user_id'])

            self.update_order_message(bot, self.deserialize(collection))

        else:
            update.message.reply_text("Uh oh - there is no ongoing order in this chat. Please /start me first.")

    def set_store(self, bot, update):
        splits = update.message.text.strip().split(' ', 1)
        if len(splits) <= 1:
            update.message.reply_text("You need to provide an argument for this command. Which store do you "
                                      "want to use? (Provide a location)")
            return

        query = splits[1]

        store = self.pizza.get_closest_store(query)
        if store is None:
            update.message.reply_text("Uh oh, I couldn't find a Domino's store at that location. Try another.")
            return

        collections = self.db['order_collections']
        collection = collections.find_one(chat=update.message.chat.id)

        if collection is not None and 'active' in collection and collection['active']:
            collection = self.deserialize(collection)
            collection['settings']['store_id'] = store['StoreID']
            collections.update(self.serialize(collection), ['chat'])

            reply_string = "I set your ongoing order to be ordered at the {} store ({}, {} {})"
            self.update_order_message(bot, collection)
        else:  # no ongoing order
            defaults = self.db['defaults']
            default_settings = defaults.find_one(chat=update.message.chat.id)
            if default_settings is None:
                default_settings = {
                    'chat': update.message.chat.id,
                    'settings': {},
                }
            else:
                default_settings = self.deserialize(default_settings)
            default_settings['settings']['store_id'] = store['StoreID']
            defaults.upsert(self.serialize(default_settings), ['chat'])
            reply_string = "I configured this chat to always order at the {} store ({}, {} {})"

        update.message.reply_text(reply_string.format(
            store['StoreName'],
            store['StreetName'],
            store['PostalCode'],
            store['City']
        ))

    def delete(self, bot, update):
        collections = self.db['order_collections']
        collection = collections.find_one(chat=update.message.chat.id)
        if not collection:
            return
        orders = self.db['orders']

        orders.delete(collection_uuid=collection['uuid'], user_id=update.message.from_user.id)

        self.update_order_message(bot, self.deserialize(collection))

    def update_order_message(self, bot, collection):
        bot.edit_message_text(
            self.get_updated_message(collection),
            chat_id=collection['chat'],
            message_id=collection['message'],
            parse_mode="markdown"
        )

    def get_updated_message(self, collection):
        text = "=== Your Orders ==="
        order_text = ""
        dominos_order_string = ""

        table = self.db['orders']
        orders = table.find(collection_uuid=collection['uuid'])

        for order in orders:
            order_text += "\n*{}*: {}\n".format(order['user_name'], order['order_text'][:403])
            dominos_order_string += "{};".format(order['order_text'].split('\n')[0])

        text += order_text
        text.strip()
        if not order_text:
            text += "\nThere are currently no orders."
            return text

        text += "\n=== My Interpretation ===\n"
        if not ('settings' in collection and 'store_id' in collection['settings']):
            text += "You have not configured a Domino's Pizza store. Please do so using the /store command."
            return text

        if dominos_order_string.endswith(';'):
            dominos_order_string = dominos_order_string[:-1]
        dominos_menu = self.pizza.get_menu_from_store(collection['settings']['store_id'])
        dominos_orders = self.pizza.parse_all_orders(dominos_order_string, dominos_menu)
        validated_orders = self.pizza.create_order(collection['settings']['store_id'], dominos_orders, dominos_menu)

        for item in validated_orders['Order']['Coupons']:
            text += "{}\n".format(dominos_menu.get_deals()[item['Code']]['Name'])

        for item in validated_orders['Order']['Products']:
            if 'AutoRemove' in item and item['AutoRemove']:
                continue
            text += "*{}* {} CHF".format(
                item['Name'] if 'Name' in item else item['Code'],
                item['Price'] if 'Price' in item else "--"
            )
            if 'Options' in item:
                text += " - "
                text += self.pizza.get_customization_string(item, dominos_menu)
            text += '\n'
            if 'StatusItems' in item:
                for status_item in item['StatusItems']:
                    text += status_item['Code']
                    text += " "
                text += '\n'
        if 'StatusItems' in validated_orders['Order']:
            text += '\nDominos reports the following issues with your order:\n'
            for status_item in validated_orders['Order']['StatusItems']:
                text += status_item['Code']
                text += " "
            text += '\n'

        return text.strip()

    @staticmethod
    def get_affirmation():
        return random.choice(AFFIRMATIONS)

    # Help command handler
    def send_help(self, bot, update):
        """Send a message when the command /help is issued."""
        helptext = "Hey! I'm an order bot. I collect orders from members of your group chat.\n" \
            "Just add me to a group chat and send me the /start command.\n" \
            "After that, anyone can send a message to the chat that @mentions me, " \
            "and I will add the content of that message to my order list.\n\n" \
            "Example: 'One pizza please @{}'\n\n" \
            "Protip: Pin the message with the orders so you don't lose it.".format(self.config['bot_name'])
        update.message.reply_text(helptext)

    # Error handler
    def error(self, bot, update, error):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, error)

    @staticmethod
    def serialize(item):
        ser = dict(item)
        if 'settings' in ser:
            ser['settings'] = json.dumps(item['settings'])
        return ser

    @staticmethod
    def deserialize(serialized):
        item = dict(serialized)
        if 'settings' in item and item['settings'] is not None:
            item['settings'] = json.loads(serialized['settings'])
        else:
            item['settings'] = {}
        return item

    def run(self, opts):
        with open(opts.config, 'r') as configfile:
            self.config = yaml.load(configfile)

        self.db = dataset.connect('sqlite:///{}'.format(self.config['db']))

        self.pizza = PizzaApi(self.config['pizza'])

        # Create the EventHandler and pass it your bot's token.
        updater = Updater(self.config['token'])

        # Get the dispatcher to register handlers
        dp = updater.dispatcher

        dp.add_handler(MentionsHandler(self.config['bot_name'], self.mention))
        dp.add_handler(CommandHandler("help", self.send_help))
        dp.add_handler(CommandHandler("start", self.start))
        dp.add_handler(CommandHandler("delete", self.delete))
        dp.add_handler(CommandHandler("store", self.set_store))

        # log all errors
        dp.add_error_handler(self.error)

        # Start the Bot
        updater.start_polling()

        # Run the bot until you press Ctrl-C or the process receives SIGINT,
        # SIGTERM or SIGABRT. This should be used most of the time, since
        # start_polling() is non-blocking and will stop the bot gracefully.
        updater.idle()


def main(opts):
    PollBot().run(opts)


if __name__ == '__main__':
    from optparse import OptionParser
    parser = OptionParser()
    parser.add_option('-c', '--config', dest='config', default='config.yml', type='string', help="Path of configuration file")
    (opts, args) = parser.parse_args()
    main(opts)
