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
from dominos import Dominos
from default import Default

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
        self.backends = {}

    def start(self, bot, update):
        """Send a message when the command /start is issued."""
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
        self.store_collection(new_collection)

    def mention(self, bot, update):
        collection = self.get_collection(update.message.chat.id)

        order_text = update.message.text.replace("@{}".format(self.config['bot_name']), "")
        if len(order_text) > 400:
            order_text = order_text[:400] + "..."
        order_text = re.sub(r'\n\s*', "\n", order_text)
        order_text.strip()
        if collection is not None and collection['active']:
            orders = self.db['orders']
            new_order = {
                'collection_uuid': collection['uuid'],
                'chat': update.message.chat.id,
                'user_id': update.message.from_user.id,
                'user_name': update.message.from_user.first_name,
                'order_text': order_text,
            }
            orders.upsert(new_order, ['chat', 'user_id'])

            self.update_order_message(bot, collection)

        else:
            update.message.reply_text("Uh oh - there is no ongoing order in this chat. Please /start me first.")

    def delete(self, bot, update):
        collection = self.get_collection(update.message.chat.id)
        if not collection:
            return
        orders = self.db['orders']

        orders.delete(collection_uuid=collection['uuid'], user_id=update.message.from_user.id)

        self.update_order_message(bot, collection)

    def set_mode(self, bot, update):
        splits = update.message.text.strip().split(' ', 1)

        modes = ""
        for i in self.backends.keys():
            modes += "*{}*: {}\n".format(i, self.backends[i].short_description)

        if len(splits) <= 1:
            update.message.reply_text("Please provide an argument for this command. "
                                      "Available modes are:\n{}".format(modes),
                                      parse_mode='markdown')
            return

        arg = splits[1].strip().lower()

        if arg not in self.backends:
            update.message.reply_text("Invalid mode. Available modes are:\n{}".format(modes),
                                      parse_mode='markdown')
            return

        collection = self.get_collection(update.message.chat.id)

        if collection is not None and 'active' in collection and collection['active']:
            collection = self.deserialize(collection)
            collection['settings']['mode'] = arg
            message = self.backends[arg].mode_selected_message
            self.store_collection(collection)

            reply_string = "I tried to configure your ongoing order.\n{}".format(message)
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
                default_settings = self.deserialize(default_settings['settings'])
            default_settings['mode'] = arg
            message = self.backends[arg].mode_selected_message
            defaults.upsert(self.serialize(default_settings), ['chat'])
            reply_string = "I tried to configure the global settings for this chat.\n{}".format(message)

        update.message.reply_text(reply_string)

    def close_order(self, bot, update):
        collection = self.get_collection(update.message.chat.id)

        if collection is not None:
            collection['active'] = False
            self.store_collection(collection)
        update.message.reply_text("I closed your ongoing order. You can always /reopen it.")

    def reopen_order(self, bot, update):
        collection = self.get_collection(update.message.chat.id)

        if collection is not None:
            collection['active'] = True
            update.message.reply_text("I reopened your ongoing order. You can now order stuff again.")
            self.store_collection(collection)
        else:
            update.message.reply_text("Uh oh, there is no order in this chat that I could reopen.")

    # Help command handler
    def send_help(self, bot, update):
        """Send a message when the command /help is issued."""
        helptext = "Hey! I'm an order bot. I collect orders from members of your group chat.\n" \
            "Just add me to a group chat and send me the /start command.\n" \
            "After that, anyone can send a message to the chat that @mentions me, " \
            "and I will add the content of that message to my order list.\n\n" \
            "Example: 'One pizza please @{}'\n\n" \
            "I support various modes. By default, I merely collect your orders, but I can " \
            "also order at Domino's Pizza, for example. Check out the /mode command to learn more.\n\n" \
            "Protip: Pin the message with the orders so you don't lose it.".format(self.config['bot_name'])
        update.message.reply_text(helptext)

    # Error handler
    def error(self, bot, update, error):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, error)

    def get_collection(self, chat_id):
        collections = self.db['order_collections']
        collection = collections.find_one(chat=chat_id)
        if collection is not None:
            return self.deserialize(collection)
        else:
            return None

    def store_collection(self, collection):
        collections = self.db['order_collections']
        collections.upsert(self.serialize(collection), ['chat'])

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

        table = self.db['orders']
        orders = table.find(collection_uuid=collection['uuid'])
        orders = list(orders)

        for order in orders:
            order_text += "\n*{}*: {}\n".format(order['user_name'], order['order_text'][:403])

        text += order_text
        text.strip()
        if not order_text:
            text += "\nThere are currently no orders."
            return text

        text += "\n"
        text += self.get_backend(collection).get_orders_as_string(collection, orders)

        return text

    @staticmethod
    def get_affirmation():
        return random.choice(AFFIRMATIONS)

    def get_backend(self, collection):
        if not ('settings' in collection and 'mode' in collection['settings']):
            return self.backends['default']
        elif not collection['settings']['mode'] in self.backends:
            return self.backends['default']
        else:
            return self.backends[collection['settings']['mode']]

    def set_store(self, bot, update):
        splits = update.message.text.strip().split(' ', 1)
        if len(splits) <= 1:
            query = ""
        else:
            query = splits[1]

        collections = self.db['order_collections']
        collection = collections.find_one(chat=update.message.chat.id)

        if collection is not None and 'active' in collection and collection['active']:
            collection = self.deserialize(collection)
            message = self.get_backend(collection).set_store(query, collection['settings'])
            collections.update(self.serialize(collection), ['chat'])

            reply_string = "I tried to configure your ongoing order.\n{}".format(message)
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
            message = self.get_backend(default_settings).set_store(query, default_settings['settings'])
            defaults.upsert(self.serialize(default_settings), ['chat'])
            reply_string = "I tried to configure the global settings for this chat.\n{}".format(message)

        update.message.reply_text(reply_string)

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

        self.backends['dominos'] = Dominos(self.config['dominos'])
        self.backends['default'] = Default(None)

        # Create the EventHandler and pass it your bot's token.
        updater = Updater(self.config['token'])

        # Get the dispatcher to register handlers
        dp = updater.dispatcher

        # General commands
        dp.add_handler(MentionsHandler(self.config['bot_name'], self.mention))
        dp.add_handler(CommandHandler("help", self.send_help))
        dp.add_handler(CommandHandler("start", self.start))

        # Order commands
        dp.add_handler(CommandHandler("delete", self.delete))

        # Collection commands
        dp.add_handler(CommandHandler("close", self.close_order))
        dp.add_handler(CommandHandler("reopen", self.reopen_order))

        # Configuration commands
        dp.add_handler(CommandHandler("mode", self.set_mode))
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
