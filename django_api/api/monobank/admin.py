from django.contrib import admin
from django.contrib.auth import get_user_model

from .models import (
    Category,
    CategoryMSO,
    Currency,
    JarTransaction,
    MonoAccount,
    MonoCard,
    MonoJar,
    MonoTransaction,
)

User = get_user_model()

admin.site.register(User)
admin.site.register(Category)
admin.site.register(Currency)
admin.site.register(CategoryMSO)
admin.site.register(MonoAccount)
admin.site.register(MonoCard)


class MonoJarModelAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "owner_name",
        "title",
        "currency",
        "formatted_balance",
        "formatted_invested",
        "formatted_goal",
        "is_budget",
        "is_active",
    ]
    search_fields = ["id", "title", "monoaccount__user__name"]
    list_filter = ["currency", "is_budget", "is_active"]

    class Meta:
        model = MonoJar


admin.site.register(MonoJar, MonoJarModelAdmin)


# admin.site.register(JarTransaction)


class MonoTransactionModelAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "formatted_time",
        "formatted_amount",
        "description",
        "formatted_balance",
    ]
    ordering = ["-time"]

    class Meta:
        model = MonoTransaction


admin.site.register(MonoTransaction, MonoTransactionModelAdmin)


class JarTransactionModelAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "owner_name",
        "jar_name",
        "formatted_time",
        "formatted_amount",
        "description",
        "formatted_balance",
    ]
    ordering = ["-time"]

    class Meta:
        model = JarTransaction


admin.site.register(JarTransaction, JarTransactionModelAdmin)
# admin.site.register(MonoCardTransaction)
# admin.site.register(MonoJarTransaction)
