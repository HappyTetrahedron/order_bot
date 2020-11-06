from telegram.ext import MessageFilter
from telegram import Message

class MentionFilter(MessageFilter):
    """
    Filters messages to only allow those which have a mention
    with the provided username
    Examples:
        Example ``MessageHandler(Filters.mention("bob"), callback_method)``
    Args:
        username: Username to check for.
    """

    def __init__(self, username: str):
        self.username = username

    def filter(self, message: Message) -> bool:
        res = False
        for entity in message.entities:
            if entity.type == "mention":
                 unicode_text = message.text.encode('utf-16')
                 # Multiply all offsets by 2 because we're still counting 8-bit units although
                 # the string is utf-16.
                 # Add 2 to first offset - one to consume the BOM, one to consume the @ character of the mention
                 # Add only 1 to the last offset, for the BOM
                 mentioned = unicode_text[(entity.offset + 2) * 2:(entity.offset + entity.length + 1) * 2]
                 if mentioned.decode('utf-16') == self.username:
                     res = True
        return res

