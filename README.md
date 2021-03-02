# order_bot
A telegram bot to collect orders inside a group chat - to make the process of collecting food orders (or similar) a bit easier.

Check out the [official instance](https://t.me/pentachoron_bot) if all you want is to use this bot.

## Usage
Simply add this bot to your group chat, then text the `/start` command to the bot and it will create a new order collection.

All group chat members can then add items to the list by mentioning the bot. E.g., `One pizza please @pentachoron_bot`

These orders are then collected in a list in the order bot's message. This makes it easy to find all the orders 
without having to meticulously read through all the messages.

To change your order, simply write another message which mentions the bot. This will _replace_ your previous order.

If you want to delete your order entirely, use the `/delete` command.

When you're all done ordering, you can `/close` the order - this will prevent anyone from making further changes.

## Advanced usage: Modes
By default, the order bot just collects all the orders in a single message and does nothing else. However, some advanced modes are available, 
which can allow you to directly send your order to a specific supplier.

Currently, only Domino's Pizza in Switzerland is supported. Feel free to contact me if you're interested in adding support for more suppliers.

To switch mode, use the `/mode` command, e.g., `/mode dominos`. If an order is open, then this specific order will be configured. If _no_ order is opened, 
then this command will instead change the default preference for the group chat you're in, and all future orders will use this mode.

### Domino's Pizza Switzerland
To activate this mode, use `/mode dominos`.

__Important:__ This bot is not officially supported by Domino's. The pizza ordering mechanism relies on a lot of reverse engineering and 
sometimes it breaks for reasons outside of my control. I occasionally update it, but it may stop working any time, and it may malfunction in any way.
I will not be liable if you accidentally order fifty pizzas.

(If you suspect the bot may have sent an order by accident, I kindly suggest calling the store to sort things out.)

Now, you will have to add some basic settings for the Domino's Pizza mode to work.

* Configure which specific Domino's store you want to order from by providing a location, e.g., `/store Zürich Universitätsstrasse`
* Configure which service method you want to use: `\method delivery` or `\method carryout` (for in-store pickup)
* Configure at what time you want the pizza: `\time 18:00`. If the store is currently open, you can also use `\time asap` for ASAP service.
* If you chose the Delivery service method, the bot needs your address: `\address Universitätsstrasse 6, 8006 Zürich`
* If you chose the Delivery service method, the bot needs your phone number: `\phone +41 079 123 45 67`
* If you chose the Delivery service method, the bot needs your email: `\email herbert@example.com`
* If you chose the Delivery service method, the bot needs your full name: `\name Herbert Example`

With all these settings configured, you can start ordering things. You can refer to any menu items by name, the pizza bot will try to figure out what you want.
Don't forget to double check if everything is correct before ordering!

Here are some examples of working pizza orders:

```
veggie dream and a coke

small hawaii bbq

large meatlovers with extra cheese

create your own with extra cheese extra mushrooms

Create your own feta, sweet corn, cherry tomatoes, herbes de provence
```

Once you're ready to order and have double checked everything, use the `/order` command to start the ordering process. 
The bot will give you a summary of what it will try to order. You can then click on the submit button to actually send the order to Domino's. 
Yes, __you will have to pay for it__. If you chose the "Delivery" service method, you will need to pay cash, as credit card payments are not supported.


## Running it yourself

Since you're here on my Github, perhaps you wanted to run your own order bot instance?
Feel free! Simply install the required python packages from `requirements.txt` and then create a config file for your bot.

The config file looks like this:
```
token: "123456789:ThisIsYourTelegramBotSecretToken1234"
db: "orders.db"
bot_name: "NameOfYourBot"

dominos:
  debug: true
  geocode:
    url: http://www.mapquestapi.com/geocoding/v1/address?key={key}&location={query}
    key: thisIsYourMapquestApiKey1234
  sourceURI: order.dominos.com
  referer: https://www.dominos.ch/pages/order/
  regionCode: CH
  language: en
  market: SWITZERLAND
  store:
    find: "https://order.golo02.dominos.com/store-locator-international/locate/store?regionCode={regioncode}&latitude={lat}&longitude={lng}"
    info: "https://order.golo02.dominos.com/power/store/{storeID}/profile"
    menu: "https://order.golo02.dominos.com/power/store/{storeID}/menu?lang={lang}&structured=true"
    responseType: "application/vnd.com.dominos.ecommerce.store-locator.response+json;version=1.2"
    deals: "https://order.golo02.dominos.com/power/store/{storeID}/coupon/{dealID}?lang={lang}"
  order:
    validate: https://order.golo02.dominos.com/power/validate-order
    price: https://order.golo02.dominos.com/power/price-order
    place: https://order.golo02.dominos.com/power/price-order
```
The `db` entry is the path of the SQLite database in which order information is stored. Provide a file name, and a sqlite file will automatically be created.

The whole `dominos` section is relevant for the Dominos mode only. If you plan to use that, you will need a [MapQuest API key](https://developer.mapquest.com/documentation/)
and add it in the `geocode` section (for address lookup).

You should not require to change anything else.  It may be possible to support Domino's ordering in 
other countries by messing with these settings, though - good luck!
