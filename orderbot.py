#!/usr/bin/env python
# -*- coding: utf-8 -*-
import random
import yaml
import logging
import dataset
import re
import json

from uuid import uuid4

from telegram import TelegramError, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, CallbackQueryHandler, MessageHandler
from mentions_handler import MentionFilter
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

    def start(self, update, context):
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

    def mention(self, update, context):
        msg = update.message if update.message is not None else update.edited_message
        collection = self.get_collection(msg.chat.id)

        order_text = msg.text.replace("@{}".format(self.config['bot_name']), "")
        if len(order_text) > 400:
            order_text = order_text[:400] + "..."
        order_text = re.sub(r'\n\s*', "\n", order_text)
        order_text.strip()
        if collection is not None and collection['active']:
            orders = self.db['orders']
            new_order = {
                'collection_uuid': collection['uuid'],
                'chat': msg.chat.id,
                'user_id': msg.from_user.id,
                'user_name': msg.from_user.first_name,
                'order_text': order_text,
            }
            orders.upsert(new_order, ['chat', 'user_id'])

            self.update_order_message(context.bot, collection)

        else:
            msg.reply_text("Uh oh - there is no ongoing order in this chat. Please /start me first.")

    def button(self, update, context):
        query = update.callback_query
        if query.data == 'cancel':
            context.bot.edit_message_text(
                text="Alright, I cancelled the order. You can keep making changes and try again, or /close it.",
                message_id=query.message.message_id,
                chat_id=query.message.chat.id
            )

        elif query.data == 'confirm':
            collection = self.get_collection(query.message.chat.id)
            if 'data' not in collection:
                # uhm?
                context.bot.edit_message_text(
                    text="There was an error of sorts, it seems... Please just try again.",
                    message_id=query.message.message_id,
                    chat_id=query.message.chat.id
                )
                return

            if 'issuer_id' in collection:
                if collection['issuer_id'] != update.callback_query.from_user.id:
                    update.callback_query.answer("Only the person who started the order can confirm it.")
                    return

            data = json.loads(collection['data'])

            table = self.db['orders']
            orders = table.find(collection_uuid=collection['uuid'])
            orders = list(orders)

            message, error = self.get_backend(collection).place_order(collection, orders, data)

            context.bot.edit_message_text(
                text=message,
                message_id=query.message.message_id,
                chat_id=query.message.chat.id,
                parse_mode='markdown'
            )

            if not error:
                collection['active'] = False
                self.store_collection(collection)

    def delete(self, update, context):
        collection = self.get_collection(update.message.chat.id)
        if not collection:
            return
        orders = self.db['orders']

        orders.delete(collection_uuid=collection['uuid'], user_id=update.message.from_user.id)

        self.update_order_message(context.bot, collection)

    def set_mode(self, update, context):
        arg = self.get_command_arg(update.message.text)

        modes = ""
        for i in self.backends.keys():
            modes += "*{}*: {}\n".format(i, self.backends[i].short_description)

        if not arg:
            update.message.reply_text("Please provide an argument for this command. "
                                      "Available modes are:\n{}".format(modes),
                                      parse_mode='markdown')
            return

        if arg not in self.backends:
            update.message.reply_text("Invalid mode. Available modes are:\n{}".format(modes),
                                      parse_mode='markdown')
            return

        def setter(settings):
            settings['mode'] = arg
            return self.backends[arg].mode_selected_message

        reply_string = self.configure_settings(context.bot, update.message.chat.id, setter)
        update.message.reply_text(reply_string)

    def set_backend_specific_setting(self, setting_key, bot, update):
        query = self.get_command_arg(update.message.text)

        settings, _ = self.get_settings(update.message.chat.id)

        def setter(_settings):
            return self.get_backend_from_settings(settings).set(setting_key, query, _settings)

        reply_string = self.configure_settings(bot, update.message.chat.id, setter)
        update.message.reply_text(reply_string)

    def print_settings(self, update, context):
        settings, is_global = self.get_settings(update.message.chat.id)
        if is_global:
            msg = "Global settings:\n"
        else:
            msg = "Collection settings:\n"
        if not settings:
            update.message.reply_text("This chat has no settings configured.")
        else:
            for k, v in settings.items():
                msg += "{}: {}\n".format(k, v)
            update.message.reply_text(msg)

    def close_order(self, update, context):
        collection = self.get_collection(update.message.chat.id)

        if collection is not None:
            collection['active'] = False
            self.store_collection(collection)
        update.message.reply_text("I closed your ongoing order. You can always /reopen it.")

    def reopen_order(self, update, context):
        collection = self.get_collection(update.message.chat.id)

        if collection is not None:
            collection['active'] = True
            update.message.reply_text("I reopened your ongoing order. You can now order stuff again.")
            self.store_collection(collection)
        else:
            update.message.reply_text("Uh oh, there is no order in this chat that I could reopen.")

    def place_order(self, update, context):
        collection = self.get_collection(update.message.chat.id)
        if collection is None \
                or 'active' not in collection \
                or not collection['active']:
            update.message.reply_text("Uh oh, looks like there is no ongoing order in this chat. "
                                      "Please /start me first.")
            return

        table = self.db['orders']
        orders = table.find(collection_uuid=collection['uuid'])
        orders = list(orders)

        message, data, error = self.get_backend(collection).get_confirmation_message(collection, orders)

        if error:
            update.message.reply_text(message)
            return

        data_string = json.dumps(data, separators=(',', ':'))

        collection['data'] = data_string
        collection['issuer_id'] = update.message.from_user.id
        self.store_collection(collection)

        inline_keyboard_items = [
            [InlineKeyboardButton("Confirm", callback_data="confirm")],
            [InlineKeyboardButton("Cancel", callback_data="cancel")],
        ]
        inline_keyboard = InlineKeyboardMarkup(inline_keyboard_items)
        update.message.reply_text(message, reply_markup=inline_keyboard, parse_mode='markdown')

    # Help command handler
    def send_help(self, update, context):
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
    def error(self, update, context):
        """Log Errors caused by Updates."""
        logger.warning('Update "%s" caused error "%s"', update, context.error)
        import traceback
        traceback.print_exception(type(context.error), context.error, context.error.__traceback__)

    def configure_settings(self, bot, chat_id, setter_func):
        collection = self.get_collection(chat_id)
        if collection is not None and 'active' in collection and collection['active']:
            message = setter_func(collection['settings'])
            self.store_collection(collection)
            reply_string = "I tried to configure your ongoing order.\n{}".format(message)
            try:
                self.update_order_message(bot, collection)
            except TelegramError as e:
                logger.warning(e)

        else:
            defaults = self.db['defaults']
            default_settings = defaults.find_one(chat=chat_id)
            if default_settings is None:
                default_settings = {
                    'chat': chat_id,
                    'settings': {},
                }
            else:
                default_settings = self.deserialize(default_settings)
            message = setter_func(default_settings['settings'])
            defaults.upsert(self.serialize(default_settings), ['chat'])
            reply_string = "I tried to configure the global settings for this chat.\n{}".format(message)
        return reply_string

    def get_settings(self, chat_id):
        collection = self.get_collection(chat_id)
        if collection is not None and 'active' in collection and collection['active']:
            return collection['settings'], False
        else:
            defaults = self.db['defaults']
            default_settings = defaults.find_one(chat=chat_id)
            if default_settings is None:
                return {}, True
            else:
                default_settings = self.deserialize(default_settings)
                return default_settings['settings'], True

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
        if 'settings' not in collection:
            return self.backends['default']
        return self.get_backend_from_settings(collection['settings'])

    def get_backend_from_settings(self, settings):
        if 'mode' not in settings:
            return self.backends['default']
        elif not settings['mode'] in self.backends:
            return self.backends['default']
        else:
            return self.backends[settings['mode']]

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

    @staticmethod
    def get_command_arg(command):
        splits = command.strip().split(' ', 1)
        if len(splits) <= 1:
            return ""
        else:
            return splits[1].strip().lower()

    def run(self, opts):
        with open(opts.config, 'r') as configfile:
            self.config = yaml.load(configfile, Loader=yaml.BaseLoader)

        self.db = dataset.connect('sqlite:///{}'.format(self.config['db']))

        self.backends['dominos'] = Dominos(self.config['dominos'])
        self.backends['default'] = Default(None)

        # Create the EventHandler and pass it your bot's token.
        updater = Updater(self.config['token'])

        # Get the dispatcher to register handlers
        dp = updater.dispatcher

        # General commands
        # dp.add_handler(MentionsHandler(self.config['bot_name'], self.mention, edited_updates=True))
        dp.add_handler(MessageHandler(MentionFilter(self.config['bot_name']), self.mention, edited_updates=True))
        dp.add_handler(CommandHandler("help", self.send_help))
        dp.add_handler(CommandHandler("start", self.start))

        # Order commands
        dp.add_handler(CommandHandler("delete", self.delete))

        # Collection commands
        dp.add_handler(CommandHandler("close", self.close_order))
        dp.add_handler(CommandHandler("reopen", self.reopen_order))
        dp.add_handler(CommandHandler("order", self.place_order))

        # Configuration commands
        dp.add_handler(CommandHandler("settings", self.print_settings))
        dp.add_handler(CommandHandler("mode", self.set_mode))

        # Backend specific configuration
        dp.add_handler(CommandHandler("store", lambda update, context:
                                      self.set_backend_specific_setting('store', context.bot, update)))
        dp.add_handler(CommandHandler("servicemethod", lambda update, context:
                                      self.set_backend_specific_setting('service_method', context.bot, update)))
        dp.add_handler(CommandHandler("method", lambda update, context:
                                      self.set_backend_specific_setting('service_method', context.bot, update)))
        dp.add_handler(CommandHandler("address", lambda update, context:
                                      self.set_backend_specific_setting('address', context.bot, update)))
        dp.add_handler(CommandHandler("name", lambda update, context:
                                      self.set_backend_specific_setting('name', context.bot, update)))
        dp.add_handler(CommandHandler("phone", lambda update, context:
                                      self.set_backend_specific_setting('phone', context.bot, update)))
        dp.add_handler(CommandHandler("email", lambda update, context:
                                      self.set_backend_specific_setting('email', context.bot, update)))
        dp.add_handler(CommandHandler("time", lambda update, context:
                                      self.set_backend_specific_setting('time', context.bot, update)))

        dp.add_handler(CallbackQueryHandler(self.button))

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
