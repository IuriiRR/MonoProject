# pyright: reportIncompatibleMethodOverride = false
# pyright: reportAttributeAccessIssue = false
# pyright: reportUnknownVariableType = false

import json
import logging
from datetime import datetime

from account.models import User as CustomUser
from django.contrib.auth import get_user_model
from django.db.models import Q
from pydantic import ValidationError
from rest_framework.decorators import action
from rest_framework.permissions import (
    AllowAny,
    BasePermission,
    IsAdminUser,
    IsAuthenticated,
)
from rest_framework.views import APIView, Response
from rest_framework.viewsets import ModelViewSet

from .models import (
    Category,
    JarTransaction,
    MonoAccount,
    MonoCard,
    MonoDataNotFound,
    MonoJar,
    MonoTransaction,
)
from .pydantic import TransactionData
from .serializers import (
    CategorySerializer,
    MonoAccountSerializer,
    MonoCardSerializer,
    MonoJarSerializer,
    MonoJarTransactionSerializer,
    MonoTransactionSerializer,
)

logger = logging.getLogger(__name__)
User: CustomUser = get_user_model()  # type: ignore


class MonoBankAccessMixin:
    """Mixin to provide common access control logic for MonoBank entities."""

    def get_accessible_user_tg_ids(self, users_param=None, with_family=False):
        """
        Get list of tg_ids that the current user can access.
        Returns all tg_ids for superusers, filtered tg_ids for regular users.
        """
        if self.request.user.is_superuser:
            if users_param and self.action == "list":
                user_ids = users_param.split(",")
                if with_family:
                    try:
                        user_ids = User.expand_tg_ids_with_family(user_ids)
                    except Exception:
                        pass
                return user_ids
            return None  # No filtering for superusers when no specific users requested

        # For non-admin users
        accessible_ids = set(
            self.request.user.get_related_tg_ids(include_self=True, recursive=False)
        )

        if users_param:
            requested_ids = set(users_param.split(","))
            if with_family:
                try:
                    requested_ids = set(User.expand_tg_ids_with_family(requested_ids))
                except Exception:
                    pass
            return list(requested_ids.intersection(accessible_ids))

        return list(accessible_ids)


class CategoryViewSet(ModelViewSet):
    serializer_class = CategorySerializer
    queryset = Category.objects.all()
    http_method_names = ["get"]

    def get_permissions(self):
        permission = IsAuthenticated()
        return [permission]


class MonoAccountViewSet(ModelViewSet):
    serializer_class = MonoAccountSerializer
    queryset = MonoAccount.objects.all()
    http_method_names = ["get", "post"]

    def get_permissions(self):
        permission = IsAdminUser()
        return [permission]


class IsOwnerOrFamilyOrAdminPermission(BasePermission):
    """
    Allows access to owners, family members, or admin users.
    """

    def has_permission(
        self, request, view
    ):  # pyright: ignore[reportIncompatibleMethodOverride]
        """
        Return `True` if permission is granted, `False` otherwise.
        """
        return bool(request.user)

    def has_object_permission(
        self, request, view, obj
    ):  # pyright: ignore[reportIncompatibleMethodOverride]
        """
        Return `True` if permission is granted, `False` otherwise.
        """
        if request.user.is_superuser:
            return True

        # Get the target user's tg_id based on object type
        if hasattr(obj, "monoaccount"):
            target_tg_id = obj.monoaccount.user.tg_id
        elif hasattr(obj, "account") and hasattr(obj.account, "monoaccount"):
            target_tg_id = obj.account.monoaccount.user.tg_id
        else:
            return False

        # Check if user is owner or family member
        user_accessible_ids = set(
            request.user.get_related_tg_ids(include_self=True, recursive=False)
        )
        return target_tg_id in user_accessible_ids


class DailyReportSchedulerApiView(APIView):
    permission_classes = [AllowAny]
    http_method_names = ["post", "delete"]

    def post(self, request):
        """Create or enable a daily task at 21:00 that sends comprehensive mono transactions report to the provided tg_id.

        Body:
        - tg_id: required, Telegram chat/user id
        """
        try:

            from django_celery_beat.models import CrontabSchedule, PeriodicTask
        except Exception as err:
            logger.error(f"Failed importing scheduler models: {err}")
            return Response({"error": "scheduler is not available"}, status=500)

        tg_id = request.data.get("tg_id")
        if not tg_id:
            return Response({"error": "tg_id is required"}, status=400)

        # Create crontab schedule for daily at 21:00
        schedule, _ = CrontabSchedule.objects.get_or_create(
            minute=0,
            hour=21,
            day_of_week="*",
            day_of_month="*",
            month_of_year="*",
        )

        task_name = f"Daily mono transactions report for TG {tg_id}"
        task_path = "monobank.tasks.send_daily_mono_transactions_report"

        periodic_task, created = PeriodicTask.objects.get_or_create(
            name=task_name,
            defaults={
                "task": task_path,
                "crontab": schedule,
                "args": json.dumps([str(tg_id)]),
                "enabled": True,
            },
        )
        if not created:
            periodic_task.interval = None
            periodic_task.crontab = schedule
            periodic_task.task = task_path
            periodic_task.args = json.dumps([str(tg_id)])
            periodic_task.enabled = True
            periodic_task.save()

        return Response(
            {
                "message": "registered",
                "task": periodic_task.name,
                "schedule": "daily at 21:00",
                "tg_id": str(tg_id),
            },
            status=201 if created else 200,
        )

    def delete(self, request):
        """Disable or delete the daily mono transactions report task for the provided tg_id.

        Body:
        - tg_id: required
        - delete: optional boolean (default False). If True, delete the task instead of disabling it.
        """
        try:
            from django_celery_beat.models import PeriodicTask
        except Exception as err:
            logger.error(f"Failed importing scheduler models: {err}")
            return Response({"error": "scheduler is not available"}, status=500)

        tg_id = request.data.get("tg_id")
        if not tg_id:
            return Response({"error": "tg_id is required"}, status=400)

        task_name = f"Daily mono transactions report for TG {tg_id}"
        task = PeriodicTask.objects.filter(name=task_name).first()
        if not task:
            return Response({"error": "task not found"}, status=404)

        should_delete = bool(request.data.get("delete"))
        if should_delete:
            task.delete()
            return Response({"message": "deleted", "task": task_name}, status=200)
        else:
            task.enabled = False
            task.save()
            return Response({"message": "disabled", "task": task_name}, status=200)


class MonoCardViewSet(MonoBankAccessMixin, ModelViewSet):
    serializer_class = MonoCardSerializer
    http_method_names = ["get"]

    def get_permissions(self):
        permission = IsAdminUser()
        if self.action in ("list", "retrieve"):
            permission = IsOwnerOrFamilyOrAdminPermission()
        return [permission]

    def get_queryset(self):
        users = self.request.query_params.get("users")

        # Base queryset with optimized joins and consistent ordering
        # Filter only active cards by default
        queryset = (
            MonoCard.objects.select_related("monoaccount__user", "currency")
            .filter(is_active=True)
            .order_by("id")
        )

        # Use mixin method for access control
        accessible_tg_ids = self.get_accessible_user_tg_ids(users)
        if accessible_tg_ids is not None:
            queryset = queryset.filter(monoaccount__user__tg_id__in=accessible_tg_ids)

        return queryset


class MonoJarViewSet(MonoBankAccessMixin, ModelViewSet):
    serializer_class = MonoJarSerializer
    http_method_names = ["get", "patch"]  # Added patch to support the new action

    def get_permissions(self):
        permission = IsAdminUser()
        if self.action in (
            "list",
            "retrieve",
            "set_budget_status",
            "set_invested",
            "available_months",
            "month_summary",
        ):
            permission = IsOwnerOrFamilyOrAdminPermission()
        return [permission]

    @action(detail=True, methods=["patch"])
    def set_invested(self, request, pk=None):
        """Set the invested amount of a jar."""
        jar = self.get_object()
        invested = request.data.get("invested")
        jar.invested = invested
        jar.save()
        return Response(status=200)

    def get_queryset(self):
        users = self.request.query_params.get("users")
        is_budget = self.request.query_params.get("is_budget")
        with_family = self.request.query_params.get("with_family")
        with_family_bool = (
            str(with_family).lower() in ("1", "true", "yes")
            if with_family is not None
            else False
        )

        # Base queryset with optimized joins and consistent ordering
        # Filter only active jars by default
        queryset = (
            MonoJar.objects.select_related("monoaccount__user", "currency")
            .filter(is_active=True)
            .order_by("id")
        )

        # Use mixin method for access control
        accessible_tg_ids = self.get_accessible_user_tg_ids(users, with_family_bool)
        if accessible_tg_ids is not None:
            queryset = queryset.filter(monoaccount__user__tg_id__in=accessible_tg_ids)

        # Filter by is_budget if provided
        if is_budget is not None:
            # Accept '1', 'true', 'True' as True, else False
            is_budget_bool = str(is_budget).lower() in ("1", "true", "yes")
            queryset = queryset.filter(is_budget=is_budget_bool)

        return queryset

    @action(detail=True, methods=["patch"])
    def set_budget_status(self, request, pk=None):
        """Set the budget status of a jar.

        Expects a boolean 'is_budget' in the request data.
        """
        jar = self.get_object()
        is_budget = request.data.get("is_budget")

        if is_budget is None:
            return Response({"error": "is_budget parameter is required"}, status=400)

        # Convert to boolean
        is_budget_bool = str(is_budget).lower() in ("1", "true", "yes")
        jar.is_budget = is_budget_bool
        jar.save()

        serializer = self.get_serializer(jar)
        return Response(serializer.data)

    @action(detail=True, methods=["get"], url_path="available-months")
    def available_months(self, request, pk=None):
        """Return list of available months for the specified jar as ISO dates 'YYYY-MM-01'."""
        jar = self.get_object()
        months = jar.get_available_months()
        return Response([d.isoformat() for d in months])

    @action(detail=True, methods=["get"], url_path="month-summary")
    def month_summary(self, request, pk=None):
        """Return monthly summary for the specified jar.

        Query params:
        - month: required string in format 'YYYY-MM-01'.
        """
        jar = self.get_object()
        month_str = request.query_params.get("month")
        if not month_str:
            return Response(
                {"error": "query param 'month' is required (e.g. 2025-07-01)"},
                status=400,
            )
        try:
            from datetime import datetime as _dt

            parsed = _dt.strptime(month_str, "%Y-%m-%d").date()
            if parsed.day != 1:
                return Response(
                    {"error": "month must be the first day of month: YYYY-MM-01"},
                    status=400,
                )
        except Exception:
            return Response(
                {"error": "invalid 'month' format, expected YYYY-MM-01"}, status=400
            )

        summary = jar.get_month_summary(parsed)
        return Response(summary)


# Removed duplicate permission class - using IsOwnerOrFamilyOrAdminPermission instead


class MonoJarTransactionViewSet(MonoBankAccessMixin, ModelViewSet):
    serializer_class = MonoJarTransactionSerializer
    http_method_names = ["get"]

    def get_permissions(self):
        permission = IsAdminUser()
        if self.action in ("list", "retrieve"):
            permission = IsOwnerOrFamilyOrAdminPermission()
        return [permission]

    def get_queryset(self):

        users = self.request.query_params.get("users")
        jar_ids = self.request.query_params.get("jars")
        time_from = self.request.query_params.get("time_from")

        # all jar transactions from all users with optimized joins
        queryset = JarTransaction.objects.select_related(
            "mcc__category", "account__monoaccount__user", "currency"
        ).order_by("-time", "id")

        # filter by jar_id
        if jar_ids:
            queryset = queryset.filter(account_id__in=jar_ids.split(","))

        # filter by time_from (inclusive), expects YYYY-MM-DD
        if time_from and isinstance(time_from, str):
            try:
                dt = datetime.strptime(time_from, "%Y-%m-%d")
                epoch_from = int(dt.timestamp())
                queryset = queryset.filter(time__gte=epoch_from)
            except Exception:
                # if parsing fails, leave queryset unchanged (optionally could return 400)
                pass

        # Use mixin method for access control
        accessible_tg_ids = self.get_accessible_user_tg_ids(users)
        if accessible_tg_ids is not None:
            queryset = queryset.filter(
                account__monoaccount__user__tg_id__in=accessible_tg_ids
            )

        return queryset

    def get_serializer(self, *args, **kwargs):
        # Allow shrinking the response fields via `fields` query parameter
        fields = None
        try:
            fields = self.request.query_params.get("fields")
        except Exception:
            pass
        if fields:
            kwargs["fields"] = fields
        return super().get_serializer(*args, **kwargs)


class MonoTransactionViewSet(MonoBankAccessMixin, ModelViewSet):
    serializer_class = MonoTransactionSerializer
    http_method_names = ["get"]

    def get_permissions(self):
        permission = IsAdminUser()
        if self.action in ("list", "retrieve"):
            permission = IsOwnerOrFamilyOrAdminPermission()
        return [permission]

    def get_queryset(self):
        users = self.request.query_params.get("users")
        card_ids = self.request.query_params.get("cards")

        # Optimized queryset with proper joins
        queryset = MonoTransaction.objects.select_related(
            "mcc__category", "account__monoaccount__user", "currency"
        ).order_by("-time", "id")

        # filter by card_id
        if card_ids:
            queryset = queryset.filter(account_id__in=card_ids.split(","))

        # Use mixin method for access control
        accessible_tg_ids = self.get_accessible_user_tg_ids(users)
        if accessible_tg_ids is not None:
            queryset = queryset.filter(
                account__monoaccount__user__tg_id__in=accessible_tg_ids
            )

        return queryset


class TransactionWebhookApiView(APIView):
    permission_classes = [AllowAny]
    http_method_names = ["post", "get"]

    def get(self, request):
        return Response(status=200)

    def _process_card_transaction(self, transaction_data: TransactionData):
        statement_item = transaction_data.statement_item
        transaction = MonoTransaction(
            account=transaction_data.account,
            id=statement_item.id,
            time=statement_item.time,
            description=statement_item.description,
            mcc=statement_item.mcc,
            original_mcc=statement_item.original_mcc,
            amount=statement_item.amount,
            operation_amount=statement_item.operation_amount,
            currency=statement_item.currency,
            commission_rate=statement_item.commission_rate,
            balance=statement_item.balance,
            hold=statement_item.hold,
            receipt_id=statement_item.receipt_id,
            cashback_amount=statement_item.cashback_amount,
            comment=statement_item.comment,
        )
        transaction.save()

    def _process_jar_transaction(self, transaction_data: TransactionData):
        statement_item = transaction_data.statement_item
        transaction = JarTransaction(
            account=transaction_data.account,
            id=statement_item.id,
            time=statement_item.time,
            description=statement_item.description,
            mcc=statement_item.mcc,
            original_mcc=statement_item.original_mcc,
            amount=statement_item.amount,
            operation_amount=statement_item.operation_amount,
            currency=statement_item.currency,
            commission_rate=statement_item.commission_rate,
            balance=statement_item.balance,
            hold=statement_item.hold,
            cashback_amount=statement_item.cashback_amount,
        )
        transaction.save()

    def post(self, request):
        user_key = request.query_params.get("token")
        if not user_key:
            logger.warning("token query param is not specified")
            return Response({"error": "token query param is not specified"}, status=403)

        try:
            parsed_data = TransactionData.parse_obj(request.data)
            if parsed_data.account.monoaccount.mono_token != user_key:
                logger.error(
                    f"invalid token or account missmatch: {user_key} for account {parsed_data.account}"
                )

                return Response(
                    {"error": "invalid token or account missmatch"}, status=403
                )

            if isinstance(parsed_data.account, MonoCard):
                if MonoTransaction.objects.filter(
                    id=parsed_data.statement_item.id
                ).exists():
                    return Response(status=200)
                self._process_card_transaction(parsed_data)
            elif isinstance(parsed_data.account, MonoJar):
                if JarTransaction.objects.filter(
                    id=parsed_data.statement_item.id
                ).exists():
                    return Response(status=200)
                self._process_jar_transaction(parsed_data)

            return Response(status=201)
        except ValidationError as err:
            logger.critical(err)
            return Response({"error": f"Wrong request structure"}, status=422)

        except MonoDataNotFound as err:
            logger.error(err)
            return Response({"error": f"Some data not found: {err}"}, status=404)


class TestEndpoint(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        # from ai_agent.agent import get_monthly_jar_transactions_tool
        # get_monthly_jar_transactions_tool("2025-04-10")
        # return
        # result = agent.invoke(
        #     "Check monotranactions spends around 2025-04-10 and monojars transactions for same period. "
        #     "Transtactotions from card should be compensated from jar or by transfer from someone else. "
        #     "Please locate card transactions which were not covered this month."
        #     "Note, that jar name and transaction description may be different. As well as sum (it may wary by 5%).")
        # result = get_jar_monthly_report_html("2025-07-10")
        # import json

        # from telegram.client import TelegramClient

        # tg = TelegramClient(os.environ.get("BOT_TOKEN", "not set bot token"))
        # tg.send_html_message(
        #     os.environ.get("ADMIN_TG_ID", "not set tg_id"), result.get("output", "{}")
        # )

        # return Response(
        #     {
        #         "input": result.get("input"),
        #         "output": result.get("output", "{}"),
        #     }
        # )
        # bar_result = bar.delay()
        # result = bar_result.get()
        # account = User.objects.get(tg_id=11111)
        # print(account)
        # account.create_cards_jars()
        # jar = MonoJar.objects.get(id="py6VpkfAYUx7w48jEU0F4EFqpkLw0to")
        # print(jar)
        # # jar.get_transactions()
        # query = JarTransaction.objects.all()
        # query = JarTransaction.objects.filter(
        #     Q(account__id="py6VpkfAYUx7w48jEU0F4EFqpkLw0to")
        #     # |
        #     # Q(monojartransaction__account__monoaccount__user__tg_id=12345)
        # )

        jars = MonoJar.objects.all()
        result = [
            [
                jar.title,
                jar.get_available_months(),
                [jar.get_month_summary(month) for month in jar.get_available_months()],
            ]
            for jar in jars
        ]
        return Response(result)

    def post(self, request):
        """Register a periodic task that sends 'hello' to a specific Telegram ID every minute.

        Body or query params:
        - tg_id: required, Telegram chat/user id
        """
        try:
            import json

            from django_celery_beat.models import IntervalSchedule, PeriodicTask
        except Exception as err:
            logger.error(f"Failed importing scheduler models: {err}")
            return Response({"error": "scheduler is not available"}, status=500)

        tg_id = request.data.get("tg_id") or request.query_params.get("tg_id")
        if not tg_id:
            return Response({"error": "tg_id is required"}, status=400)

        # Ensure we have an every-1-minute interval
        schedule, _ = IntervalSchedule.objects.get_or_create(
            every=1, period=IntervalSchedule.MINUTES
        )

        task_name = f"Send hello to TG {tg_id}"
        task_path = "monobank.tasks.send_hello_to_tg"

        # Create or update the periodic task for this tg_id
        periodic_task, created = PeriodicTask.objects.get_or_create(
            name=task_name,
            defaults={
                "task": task_path,
                "interval": schedule,
                "args": json.dumps([str(tg_id)]),
                "enabled": True,
            },
        )
        if not created:
            periodic_task.crontab = None
            periodic_task.interval = schedule
            periodic_task.task = task_path
            periodic_task.args = json.dumps([str(tg_id)])
            periodic_task.enabled = True
            periodic_task.save()

        return Response(
            {
                "message": "registered",
                "task": periodic_task.name,
                "every": 1,
                "period": "minutes",
                "tg_id": str(tg_id),
            },
            status=201 if created else 200,
        )
