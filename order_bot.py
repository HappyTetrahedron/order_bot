#!/usr/bin/env python
# -*- coding: utf-8 -*-
import random
import yaml
import logging
import dataset
import re

from uuid import uuid4
from telegram.ext import Updater, CommandHandler
from mentions_handler import MentionsHandler

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

    def start(self, bot, update):
        """Send a message when the command /start is issued."""
        if update.message.chat.type == 'private':
            update.message.reply_text('Hi! I\'m most useful inside a group chat, so just add me there!')
        else:
            table = self.db['order_collections']

            new_collection = {
                'chat': update.message.chat.id,
                'uuid': str(uuid4()),
            }

            msg = update.message.reply_text('{}! I will now start collecting your orders! '
                                            'Send a message that @mentions me and I '
                                            'will add it to the list.'.format(self.get_affirmation()),
                                            quote=False)

            new_collection['message'] = msg.message_id
            table.upsert(new_collection, ['chat'])

    def mention(self, bot, update):
        collections = self.db['order_collections']
        collection = collections.find_one(chat=update.message.chat.id)

        order_text = update.message.text.replace("@{}".format(self.config['bot_name']), "")
        if len(order_text) > 400:
            order_text = order_text[:400] + "..."
        order_text = re.sub(r'\n+', "\n", order_text)
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

            bot.edit_message_text(
                self.get_updated_message(collection),
                chat_id=collection['chat'],
                message_id=collection['message'],
                parse_mode="markdown"
            )

        else:
            update.message.reply_text("Uh oh - there is no ongoing order in this chat. Please /start me first.")

    def get_updated_message(self, collection):
        text = "=== Your Orders ==="

        table = self.db['orders']
        orders = table.find(collection_uuid=collection['uuid'])

        for order in orders:
            text += "\n**{}:** {}\n".format(order['user_name'], order['order_text'][:403])

        text.strip()
        return text

    def get_affirmation(self):
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

    def run(self, opts):
        with open(opts.config, 'r') as configfile:
            self.config = yaml.load(configfile)

        self.db = dataset.connect('sqlite:///{}'.format(self.config['db']))

        # Create the EventHandler and pass it your bot's token.
        updater = Updater(self.config['token'])

        # Get the dispatcher to register handlers
        dp = updater.dispatcher

        dp.add_handler(MentionsHandler(self.config['bot_name'], self.mention))
        dp.add_handler(CommandHandler("help", self.send_help))
        dp.add_handler(CommandHandler("start", self.start))

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
