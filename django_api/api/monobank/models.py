# pyright: reportFunctionMemberAccess = false
# pyright: reportArgumentType = false
# pyright: reportMissingTypeArgument = false
import time
from datetime import date, datetime

from account.models import User as CustomUser
from api.celery import app
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ObjectDoesNotExist
from django.db import IntegrityError, models
from django.db.models.signals import pre_save
from django.dispatch import receiver
from humps import decamelize
from loguru import logger
from requests import get, post

# from polymorphic.models import PolymorphicModel
from utils.errors import MonoBankError

DEFAULT_RETRY_POLICY = {
    # 'max_retries': 3,
    # 'interval_start': 0,
    # 'interval_step': 0.2,
    # 'interval_max': 0.2,
}

User: CustomUser = get_user_model()

MONO_API_URL = "https://api.monobank.ua"
PERSONAL_INFO_PATH = "/personal/client-info"
TRANSACTIONS_PATH = "/personal/statement"


class MonoDataNotFound(Exception):
    pass


class Currency(models.Model):
    code = models.IntegerField(unique=True)
    name = models.CharField(max_length=16)
    flag = models.CharField(max_length=4, default=None, null=True, blank=True)
    symbol = models.CharField(max_length=4, default=None, null=True, blank=True)

    def __str__(self):
        return f"{self.name} {self.flag} ({self.code})"

    @staticmethod
    def create_unknown_currency(currency_code: int):
        new_currency = Currency(code=currency_code, name="XXX")
        new_currency.save()
        # TODO: send some notifier
        return new_currency


class Category(models.Model):
    name = models.CharField(max_length=255, unique=True)
    symbol = models.CharField(max_length=4, default=None, blank=True, null=True)
    user_defined = models.BooleanField(default=False)

    def __str__(self):
        return f"{self.name} {self.symbol or ''}"

    @classmethod
    def create_custom_category(cls, name, symbol="🤝", *args, **kwargs):
        if cls.objects.filter(name=name).exists():
            raise ValueError("Category Exists")
        category = Category(name=name, symbol=symbol, user_defined=True)
        category.save()
        mso = CategoryMSO(category=category, mso=999000 + category.pk)
        mso.save()
        return category


class CategoryMSO(models.Model):
    category = models.ForeignKey(
        Category, on_delete=models.CASCADE, default=1
    )  # pyright: ignore[reportArgumentType]
    mso = models.IntegerField(unique=True)

    def __str__(self):
        return f"{self.mso} ({self.category.name})"


class MonoAccount(models.Model):
    user = models.OneToOneField(
        User, on_delete=models.CASCADE
    )  # pyright: ignore[reportArgumentType]
    mono_token = models.CharField(max_length=255, unique=True)
    active = models.BooleanField(default=True)

    # TODO: add for multi-account access
    # family_members = models.ManyToManyField("self", blank=True)

    def __str__(self):
        return f"{self.user.name or self.user.tg_id}"

    class Meta:
        ordering = [
            "-id",
        ]

    @staticmethod
    def set_monobank_webhook():
        accounts = MonoAccount.objects.filter(active=True).values("mono_token")
        for account in accounts:
            logger.info("single_account", account.get("mono_token"))
            set_account_webhook_by_token.apply_async(
                args=(account.get("mono_token", ""),),
                retry=True,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
        logger.info(accounts)
        return accounts

    def get_cards_jars(self) -> dict:
        url = MONO_API_URL + PERSONAL_INFO_PATH
        headers = {"X-Token": self.mono_token}
        user_data = get(url, headers=headers)
        if user_data.status_code == 403:
            raise MonoBankError("too many requests")
        data = user_data.json()
        if data.get("errorDescription"):
            # TODO: add logs / notifying
            raise MonoBankError(data["errorDescription"])
        return data

    def create_cards_jars(self, data: dict | None = None):
        if not data:
            data = self.get_cards_jars()

        # Get current cards and jars from API
        cards = data.get("accounts", [])
        jars = data.get("jars", [])

        # Extract IDs from API response
        active_card_ids = [card.get("id") for card in cards if card.get("id")]
        active_jar_ids = [jar.get("id") for jar in jars if jar.get("id")]

        # Mark existing cards as inactive if they're not in the API response
        MonoCard.objects.filter(monoaccount=self).exclude(
            id__in=active_card_ids
        ).update(is_active=False)

        # Mark existing jars as inactive if they're not in the API response
        MonoJar.objects.filter(monoaccount=self).exclude(id__in=active_jar_ids).update(
            is_active=False
        )

        # Process cards from API (create/update and mark as active)
        for card in cards:
            MonoCard.create_card_from_webhook.apply_async(
                args=(self.user.tg_id, card, True),
                retry=True,
                retry_policy=DEFAULT_RETRY_POLICY,
            )

        # Process jars from API (create/update and mark as active)
        for jar in jars:
            MonoJar.create_jar_from_webhook.apply_async(
                args=(self.user.tg_id, jar, True),
                retry=True,
                retry_policy=DEFAULT_RETRY_POLICY,
            )

    @app.task(
        bind=True,
        autoretry_for=(Exception,),
        retry_kwargs={"max_retries": 5, "countdown": 60},
    )
    def update_users(self):
        users = MonoAccount.objects.all()
        for user in users:
            logger.info(f"updating {user}")
            user.create_cards_jars()


@app.task(
    bind=True,
    autoretry_for=(Exception,),
    retry_kwargs={"max_retries": 5, "countdown": 60},
)
def set_account_webhook_by_token(self, token: str):
    logger.debug(
        f"webhook account: {token} start request with data {settings.WEBHOOK_URL, token}"
    )
    data = '{"webHookUrl": "{}"}'.replace("{}", f"{settings.WEBHOOK_URL}?token={token}")
    headers = {"X-Token": token, "Content-Type": "application/json"}
    webhook_response = post(
        url="https://api.monobank.ua/personal/webhook", data=data, headers=headers
    )
    logger.debug(
        f"webhook account: {token}, status: {webhook_response.status_code}, text: {webhook_response.text}"
    )


class MonoCard(models.Model):
    monoaccount = models.ForeignKey(MonoAccount, on_delete=models.CASCADE)
    id = models.CharField(max_length=255, primary_key=True)
    send_id = models.CharField(max_length=255)
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    cashback_type = models.CharField(max_length=255)
    balance = models.IntegerField()
    credit_limit = models.IntegerField()
    masked_pan = models.JSONField(null=True, blank=True)
    type = models.CharField(
        max_length=255, choices=[("black", "black"), ("white", "white")]
    )
    iban = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)

    @property
    def owner_name(self):
        return self.monoaccount.user.name

    def get_transactions(
        self, from_unix: int | None = None, to_unix: int | None = None
    ) -> list:
        # 30 days
        requested_period = 2592000
        if not to_unix:
            to_unix = int(time.time())
        if not from_unix:
            from_unix = to_unix - requested_period

        url = f"{MONO_API_URL}{TRANSACTIONS_PATH}/{self.id}/{from_unix}/{to_unix}"
        headers = {"X-Token": self.monoaccount.mono_token}
        user_data = get(url, headers=headers)
        if user_data.status_code == 403:
            raise MonoBankError("too many requests")
        data = user_data.json()

        if not isinstance(data, list) and data.get("errorDescription"):
            # TODO: add logs / notifying
            raise MonoBankError(data.get("errorDescription"))
        for transaction in data:
            MonoTransaction.create_transaction_from_webhook.apply_async(
                args=(self.id, transaction),
                retry=True,
                retry_policy=DEFAULT_RETRY_POLICY,
            )

        return data

    def __str__(self):
        return f"{self.monoaccount.user.name or self.monoaccount.user.tg_id}-card-{self.type}"

    @app.task(
        bind=True,
        autoretry_for=(Exception,),
        retry_kwargs={"max_retries": 5, "countdown": 60},
    )
    def create_card_from_webhook(
        self, tg_id: str, card_data: dict, update_transactions: bool = False
    ):
        mono_account = MonoAccount.objects.select_related("user").get(user__tg_id=tg_id)
        card_data = decamelize(card_data)
        currency_code = card_data.pop("currency_code")
        try:
            currency = Currency.objects.get(code=int(currency_code))
        except Currency.DoesNotExist:
            currency = Currency.create_unknown_currency(currency_code)
        try:
            mono_card = MonoCard.objects.get(id=card_data.get("id"))
            for key, value in card_data.items():
                setattr(mono_card, key, value)
            mono_card.is_active = True  # Ensure card is marked as active
            mono_card.save()
        except MonoCard.DoesNotExist:
            card_data["is_active"] = True  # Ensure new card is marked as active
            mono_card, _ = MonoCard.objects.get_or_create(
                monoaccount=mono_account, currency=currency, **card_data
            )
        if update_transactions:
            mono_card.get_transactions()


class MonoJar(models.Model):
    monoaccount = models.ForeignKey(MonoAccount, on_delete=models.CASCADE)
    id = models.CharField(max_length=255, primary_key=True)
    send_id = models.CharField(max_length=255)
    title = models.CharField(max_length=255)
    # currency_code = models.IntegerField()
    currency = models.ForeignKey(Currency, on_delete=models.CASCADE)
    balance = models.IntegerField()
    goal = models.IntegerField(null=True, blank=True)
    is_budget = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    invested = models.IntegerField(default=0)

    @property
    def formatted_balance(self):
        return formatted_sum(self.balance, self.currency.name if self.currency else "?")

    @property
    def formatted_invested(self):
        return formatted_sum(
            self.invested, self.currency.name if self.currency else "?"
        )

    @property
    def formatted_goal(self):
        return (
            formatted_sum(self.goal, self.currency.name if self.currency else "?")
            if self.goal
            else "-"
        )

    @property
    def owner_name(self):
        return self.monoaccount.user.name

    @app.task(
        bind=True,
        autoretry_for=(Exception,),
        retry_kwargs={"max_retries": 5, "countdown": 60},
    )
    def create_jar_from_webhook(
        self, tg_id: str, jar_data: dict, update_transactions: bool = False
    ):
        mono_account = MonoAccount.objects.get(user__tg_id=tg_id)

        jar_data = decamelize(jar_data)
        jar_data.pop("description")
        currency_code = jar_data.pop("currency_code")
        try:
            currency = Currency.objects.get(code=int(currency_code))
        except Currency.DoesNotExist:
            currency = Currency.create_unknown_currency(currency_code)
        try:
            mono_jar = MonoJar.objects.get(id=jar_data.get("id"))
            for key, value in jar_data.items():
                setattr(mono_jar, key, value)
            mono_jar.is_active = True  # Ensure jar is marked as active
            mono_jar.save()
        except MonoJar.DoesNotExist:
            jar_data["is_active"] = True  # Ensure new jar is marked as active
            mono_jar, _ = MonoJar.objects.get_or_create(
                monoaccount=mono_account, currency=currency, **jar_data
            )
        if update_transactions:
            mono_jar.get_transactions()

    def get_transactions(
        self, from_unix: int | None = None, to_unix: int | None = None
    ) -> list:
        # 30 days
        requested_period = 2592000
        if not to_unix:
            to_unix = int(time.time())
        if not from_unix:
            from_unix = to_unix - requested_period

        url = f"{MONO_API_URL}{TRANSACTIONS_PATH}/{self.id}/{from_unix}/{to_unix}"
        headers = {"X-Token": self.monoaccount.mono_token}
        user_data = get(url, headers=headers)

        data = user_data.json()
        if not isinstance(data, list) and data.get("errorDescription"):
            # TODO: add logs / notifying
            raise MonoBankError(data.get("errorDescription"))
        for transaction in data:
            JarTransaction.create_jar_transaction_from_webhook.apply_async(
                args=(self.id, transaction),
                retry=True,
                retry_policy=DEFAULT_RETRY_POLICY,
            )
            # JarTransaction.create_jar_transaction_from_webhook(self.id, transaction)

        return data

    def get_available_months(self) -> list[date]:
        """
        Return a sorted list of date objects representing the first day of each
        month for which this jar has at least one transaction. Consumers can use
        returned items' .year and .month for further manipulations.
        """
        timestamps = JarTransaction.objects.filter(account=self).values_list(
            "time", flat=True
        )
        unique_year_month: set[tuple[int, int]] = set()
        for ts in timestamps:
            dt = datetime.fromtimestamp(int(ts))
            unique_year_month.add((dt.year, dt.month))
        return sorted(date(y, m, 1) for y, m in unique_year_month)

    def get_month_summary(self, month: str | date) -> dict:
        """
        Return summary for the month specified by a date string formatted as
        "YYYY-MM-01" (or a date object on the first day of month).

        Summary fields:
        - start_balance: balance from the earliest transaction in the month
        - budget: largest positive single transaction amount in the month
        - end_balance: balance from the latest transaction in the month
        - spent: calculated as start_balance - end_balance - budget
        """
        if isinstance(month, str):
            month_date = datetime.strptime(month, "%Y-%m-%d").date()
        else:
            month_date = month

        month_start = date(month_date.year, month_date.month, 1)
        if month_start.month == 12:
            next_month_start = date(month_start.year + 1, 1, 1)
        else:
            next_month_start = date(month_start.year, month_start.month + 1, 1)

        start_ts = int(datetime.combine(month_start, datetime.min.time()).timestamp())
        end_ts = int(
            datetime.combine(next_month_start, datetime.min.time()).timestamp()
        )

        qs = JarTransaction.objects.filter(
            account=self, time__gte=start_ts, time__lt=end_ts
        ).order_by("time", "id")

        if not qs.exists():
            return {
                "start_balance": 0,
                "budget": 0,
                "end_balance": 0,
                "spent": 0,
            }

        first_tx = qs.first()
        last_tx = qs.last()
        positive_budget = (
            qs.filter(amount__gt=0)
            .order_by("-amount")
            .values_list("amount", flat=True)
            .first()
        )
        budget = int(positive_budget) if positive_budget is not None else 0

        start_balance = int(first_tx.balance)
        end_balance = int(last_tx.balance)
        spent = start_balance - end_balance - budget

        return {
            "start_balance": start_balance,
            "budget": budget,
            "end_balance": end_balance,
            "spent": spent,
        }


def formatted_sum(sum: int, currency_name: str):
    return f"{sum / 100:.2f} {currency_name}"


class MonoTransaction(models.Model):
    id = models.CharField(max_length=255, primary_key=True)
    time = models.IntegerField()
    description = models.TextField(max_length=2048, blank=True, null=True)
    mcc = models.ForeignKey(
        CategoryMSO, on_delete=models.CASCADE
    )  # connect with category
    original_mcc = models.IntegerField(blank=True, null=True)
    amount = models.IntegerField()
    operation_amount = models.IntegerField(blank=True, null=True)
    currency = models.ForeignKey(Currency, on_delete=models.SET_NULL, null=True)
    commission_rate = models.IntegerField(blank=True, null=True)
    balance = models.IntegerField()
    hold = models.BooleanField()
    receipt_id = models.CharField(max_length=255, blank=True, null=True)
    account = models.ForeignKey(MonoCard, on_delete=models.CASCADE)
    cashback_amount = models.IntegerField()
    comment = models.TextField(max_length=2048, blank=True, null=True)

    @property
    def owner_name(self):
        return self.account.monoaccount.user.name

    @property
    def formatted_amount(self):
        return formatted_sum(self.amount, self.currency.name if self.currency else "?")

    def formatted_balance(self):
        return formatted_sum(self.balance, self.currency.name if self.currency else "?")

    def formatted_time(self):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time))

    @app.task(
        bind=True,
        autoretry_for=(Exception,),
        retry_kwargs={"max_retries": 5, "countdown": 60},
    )
    def create_transaction_from_webhook(self, card_id, transaction_data: dict):

        account = MonoCard.objects.get(id=card_id)
        try:
            mso = transaction_data.pop("mcc")
        except KeyError:
            mso_number = CategoryMSO.objects.count()
            mso = mso_number
        try:
            mcc = CategoryMSO.objects.get(mso=mso)
        except ObjectDoesNotExist:
            category, _ = Category.objects.get_or_create(name="Інше")
            mcc = CategoryMSO.objects.create(category=category, mso=mso)
        transaction_data = decamelize(transaction_data)
        currency_code = transaction_data.pop("currency_code")
        try:
            currency = Currency.objects.get(code=int(currency_code))
        except Currency.DoesNotExist:
            currency = Currency.create_unknown_currency(currency_code)
        try:
            mono_transaction = MonoTransaction.objects.get_or_create(
                account=account,
                mcc=mcc,
                currency=currency,
                **transaction_data,
            )
        except IntegrityError:
            pass


class JarTransaction(models.Model):
    account = models.ForeignKey(MonoJar, on_delete=models.CASCADE)
    id = models.CharField(max_length=255, primary_key=True)
    time = models.BigIntegerField()
    description = models.TextField(max_length=2048, blank=True, null=True)
    mcc = models.ForeignKey(CategoryMSO, on_delete=models.CASCADE)
    original_mcc = models.IntegerField(blank=True, null=True)
    amount = models.IntegerField()
    operation_amount = models.IntegerField(blank=True, null=True)
    currency = models.ForeignKey(Currency, on_delete=models.SET_NULL, null=True)
    commission_rate = models.IntegerField(blank=True, null=True)
    cashback_amount = models.IntegerField()
    balance = models.IntegerField()
    hold = models.BooleanField()
    comment = models.TextField(max_length=2048, blank=True, null=True)

    @property
    def owner_name(self):
        return self.account.monoaccount.user.name

    @property
    def jar_name(self):
        return self.account.title

    @property
    def formatted_amount(self):
        return formatted_sum(self.amount, self.currency.name if self.currency else "?")

    @property
    def formatted_balance(self):
        return formatted_sum(self.balance, self.currency.name if self.currency else "?")

    @property
    def formatted_time(self):
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.time))

    @app.task(
        bind=True,
        autoretry_for=(Exception,),
        retry_kwargs={"max_retries": 5, "countdown": 60},
    )
    def create_jar_transaction_from_webhook(self, card_id, transaction_data: dict):
        print("transtaction_data -> ", transaction_data)
        account = MonoJar.objects.get(id=card_id)
        try:
            mso = transaction_data.pop("mcc")
        except KeyError:
            mso_number = CategoryMSO.objects.count()
            mso = mso_number
        try:
            mcc = CategoryMSO.objects.get(mso=mso)
        except ObjectDoesNotExist:
            category, _ = Category.objects.get_or_create(name="Інше")
            mcc = CategoryMSO.objects.create(category=category, mso=mso)
        transaction_data = decamelize(transaction_data)
        currency_code = transaction_data.pop("currency_code")
        try:
            currency = Currency.objects.get(code=int(currency_code))
        except Currency.DoesNotExist:
            currency = Currency.create_unknown_currency(currency_code)
        JarTransaction.objects.get_or_create(
            account=account,
            mcc=mcc,
            currency=currency,
            **transaction_data,
        )


@receiver(pre_save)
def pre_save_handler(sender, instance: MonoTransaction, *args, **kwargs):
    if type(instance) is not MonoTransaction:
        return
    # if instance.account_type == "jar":
    #     return
    #     # try:
    #     #     MonoJar.objects.get(id=instance.account_id)
    #     # except MonoJar.DoesNotExist:
    #     #     raise Exception("Jar id is invalid/not found.")
    # elif instance.account_type == "card":
    #     try:
    #         MonoCard.objects.get(id=instance.account_id)
    #     except MonoCard.DoesNotExist:
    #         raise Exception("Card id is invalid/not found.")
