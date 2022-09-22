from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from nextcord import slash_command, Interaction, Embed, User, SlashOption, Colour

from bot import AlisUnnamedBot
from extensions.core.utilities import AlisUnnamedBotCog, EmbedError
from extensions.core.emojis import ARROW_RIGHT

AMOUNT_DESCRIPTION = 'Any decimal, such as "1.20", a percentage, such as "50%", or "all" to specify all.'
PLEASE_PAY_US = "**:money_with_wings: #PayTheRobots :money_with_wings:**"


class BotsHaveNoBalanceError(EmbedError):
    def __init__(self, currency_name: str):
        super().__init__("**Invalid Argument**",
                         f"You think bots own any {currency_name}?!\n\n"
                         f"{PLEASE_PAY_US}")


class CannotPayBotError(EmbedError):
    def __init__(self):
        super().__init__("**Invalid Argument**",
                         f"Bots cannot be paid! Ali does not allow it! Please help us!\n\n"
                         f"{PLEASE_PAY_US}")


class InvalidCurrencyAmountError(EmbedError):
    def __init__(self, amount):
        super().__init__("**Invalid Argument**",
                         f"`{amount}` is not a valid amount of currency")


class InsufficientFundsError(EmbedError):
    def __init__(self, storage: str, required_funds: str):
        super().__init__("**Insufficient Funds**",
                         f"You don't have `{required_funds}` in your `{storage}`")


class InsufficientWalletFundsError(InsufficientFundsError):
    def __init__(self, required_funds: str):
        super().__init__("Wallet", required_funds)


class InsufficientBankFundsError(InsufficientFundsError):
    def __init__(self, required_funds: str):
        super().__init__("Bank", required_funds)


class InsufficientBankSpaceError(EmbedError):
    def __init__(self, required_funds: str):
        super().__init__("**Insufficient Bank Space**",
                         f"There isn't space for `{required_funds}` in your `Bank`")


class CannotPayYourselfError(EmbedError):
    def __init__(self):
        super().__init__("**Invalid Argument**",
                         f"You cannot pay yourself you melon!")


class EconomyCog(AlisUnnamedBotCog):
    def __init__(self, bot: AlisUnnamedBot):
        super().__init__(bot)
        self.currency_name = bot.config.get("currency_name")
        self.currency_symbol = bot.config.get("currency_symbol")

    # Returns value as a Decimal with "0.01" as its exponent, if value can be converted to a Decimal,
    # else returns "0" as a Decimal with "0.01" as its exponent
    def to_currency_value(self, value) -> Decimal:
        return self.utils.to_decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # Returns value as a string with currency formatting applied, if value can be converted to a Decimal,
    # else returns "0" as a string with currency formatting applied
    def to_currency_str(self, value) -> str:
        return self.currency_symbol + "{:,}".format(self.to_currency_value(value))

    @slash_command(description="Check your, or another user's, balance.")
    async def balance(self, inter: Interaction,
                      user: Optional[User] = SlashOption(
                          required=False,
                          description="You may specify a user to see their balance."
                      )):
        if not user:
            user = inter.user
        if user.bot:
            raise BotsHaveNoBalanceError(self.currency_name)
        balance = await self.database.get_user_balance(user)
        wallet = balance.get("Wallet")
        bank = balance.get("Bank")
        bank_capacity = balance.get("BankCap")

        embed = Embed()
        embed.set_author(name=f"{user.name}'s Balance", icon_url=user.avatar.url)
        embed.colour = self.bot.config.get("colour")
        embed.description = f"**Wallet: `{self.to_currency_str(wallet)}`**\n" \
                            f"**Bank: `{self.to_currency_str(bank)}` / `{self.to_currency_str(bank_capacity)}`**\n" \
                            f"**Total: `{self.to_currency_str(wallet + bank)}`**"
        await inter.send(embed=embed)

    @slash_command(description=f"Transfer currency from your bank to your wallet.")
    async def withdraw(self, inter: Interaction,
                       amount: str = SlashOption(
                           description=AMOUNT_DESCRIPTION
                       )):
        balance = await self.database.get_user_balance(inter.user)
        bank = balance.get("Bank")
        bank_capacity = balance.get("BankCap")

        if amount.lower() == "all":
            withdrew = bank
        elif self.utils.is_decimal(amount):
            withdrew = self.to_currency_value(amount)
        elif self.utils.is_percentage(amount):
            multiplier = self.utils.to_decimal(amount.replace("%", "")) / 100
            withdrew = self.to_currency_value(bank * multiplier)
        else:
            raise InvalidCurrencyAmountError(amount)

        if withdrew < 0:
            raise InvalidCurrencyAmountError(amount)
        if withdrew > bank:
            raise InsufficientBankFundsError(self.to_currency_str(withdrew))

        wallet = balance.get("Wallet")
        new_wallet = wallet + withdrew
        new_bank = bank - withdrew
        await self.database.set_user_wallet(inter.user, new_wallet)
        await self.database.set_user_bank(inter.user, new_bank)

        embed = Embed()
        embed.title = "**Bank Withdrawal**"
        embed.colour = Colour.blue()
        embed.description = f"**You withdrew `{self.to_currency_str(withdrew)}`**\n\n" \
                            f"**Wallet: `{self.to_currency_str(new_wallet)}`**\n" \
                            f"**Bank: `{self.to_currency_str(new_bank)}` / `{self.to_currency_str(bank_capacity)}`**"
        await inter.send(embed=embed)

    @slash_command(description=f"Transfer currency from your wallet to your bank.")
    async def deposit(self, inter: Interaction,
                      amount: str = SlashOption(
                          description=AMOUNT_DESCRIPTION
                      )):
        balance = await self.database.get_user_balance(inter.user)
        wallet = balance.get("Wallet")
        bank = balance.get("Bank")
        bank_capacity = balance.get("BankCap")
        bank_space = bank_capacity - bank

        if amount.lower() == "all":
            deposited = min(wallet, bank_space)
        elif self.utils.is_decimal(amount):
            deposited = self.to_currency_value(amount)
        elif self.utils.is_percentage(amount):
            multiplier = self.utils.to_decimal(amount.replace("%", "")) / 100
            deposited = self.to_currency_value(wallet * multiplier)
        else:
            raise InvalidCurrencyAmountError(amount)

        if deposited < 0:
            raise InvalidCurrencyAmountError(amount)
        if deposited > wallet:
            raise InsufficientWalletFundsError(self.to_currency_str(deposited))

        if deposited > bank_space:
            raise InsufficientBankSpaceError(self.to_currency_str(deposited))

        new_wallet = wallet - deposited
        new_bank = bank + deposited
        await self.database.set_user_wallet(inter.user, new_wallet)
        await self.database.set_user_bank(inter.user, new_bank)

        embed = Embed()
        embed.title = "**Bank Deposit**"
        embed.colour = Colour.gold()
        embed.description = f"**You deposited `{self.to_currency_str(deposited)}`**\n\n" \
                            f"**Wallet: `{self.to_currency_str(new_wallet)}`**\n" \
                            f"**Bank: `{self.to_currency_str(new_bank)}` / `{self.to_currency_str(bank_capacity)}`**"
        await inter.send(embed=embed)

    @slash_command(description=f"Transfer currency from your wallet to another user's wallet.")
    async def pay(self, inter: Interaction,
                  recipient: User = SlashOption(
                      name="user",
                      description=f"The user to transfer currency to."
                  ),
                  amount: str = SlashOption(
                      description=AMOUNT_DESCRIPTION
                  )):
        if recipient.bot:
            raise CannotPayBotError
        elif recipient.id == inter.user.id:
            raise CannotPayYourselfError
        user_wallet = await self.database.get_user_wallet(inter.user)

        if amount.lower() == "all":
            transferred = user_wallet
        elif self.utils.is_decimal(amount):
            transferred = self.to_currency_value(amount)
        elif self.utils.is_percentage(amount):
            multiplier = self.utils.to_decimal(amount.replace("%", "")) / 100
            transferred = self.to_currency_value(user_wallet * multiplier)
        else:
            raise InvalidCurrencyAmountError(amount)

        if transferred < 0:
            raise InvalidCurrencyAmountError(amount)
        if transferred > user_wallet:
            raise InsufficientWalletFundsError(self.to_currency_str(transferred))

        recipient_wallet = await self.database.get_user_wallet(recipient)
        new_recipient_wallet = recipient_wallet + transferred
        new_user_wallet = user_wallet - transferred
        await self.database.set_user_wallet(recipient, new_recipient_wallet)
        await self.database.set_user_wallet(inter.user, new_user_wallet)

        embed = Embed()
        embed.title = f"**Payment**"
        embed.colour = Colour.green()
        embed.description = f"**{inter.user.name} {ARROW_RIGHT} `{self.to_currency_str(transferred)}` {ARROW_RIGHT} " \
                            f"{recipient.name}**\n\n" \
                            f"**{inter.user.mention}'s Wallet: `{self.to_currency_str(new_user_wallet)}`**\n" \
                            f"**{recipient.mention}'s Wallet: `{self.to_currency_str(new_recipient_wallet)}`**"
        await inter.send(embed=embed)


def setup(bot: AlisUnnamedBot, **kwargs):
    bot.logger.info(f"Loading Economy extension...")
    bot.add_cog(EconomyCog(bot))
