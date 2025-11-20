# pyright: reportInvalidStringEscapeSequence = false
# pyright: reportArgumentType = false

import io
import logging
from datetime import datetime, timedelta

import matplotlib
import sentry_sdk
from aiogram import Bot, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.dispatcher import Dispatcher
from aiogram.types import ParseMode
from aiogram.utils.executor import start_polling
from aiogram.utils.markdown import code, text
from config import get_config
from keyboard_manager import KeyboardManager
from loguru import logger
from request_manager import RequestManager
from states import FamilyStates, MonotokenStates
from utils import generate_password, get_jar_data

# Use a non-interactive backend suitable for servers/containers
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import ticker as mticker

PASSWORD_LENGTH = 16

kbm = KeyboardManager()

# logger.add(sys.stdout, format="{time} {level} {message}", level="INFO")
logger.add(
    "logs.log", rotation="1 week", format="{time} {level} {message}", level="INFO"
)

from aiogram.types import InlineKeyboardButton, InputFile

# load_dotenv()
config = get_config()
rm = RequestManager(config)

if config.SENTRY_DSN and config.SENTRY_DSN != "NOT_SET":
    sentry_sdk.init(
        dsn=config.SENTRY_DSN,
        traces_sample_rate=1.0,
    )

bot = Bot(token=config.BOT_TOKEN)
dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

logger.info("Starting Bot")


# INFO COMMANDS
@dp.message_handler(state="*", commands=["start"])
async def start(message: types.Message):
    text = "Hi, my young monouser.\nHere you can update your Monobank experience.\nTry /help to get more info or click /register to start"
    await bot.send_message(message.chat.id, text)


@dp.message_handler(state="*", commands=["help"])
async def help(message: types.Message):
    has_user = False
    has_account = False
    available_commands = """
    /help - check available options
    """
    resp = rm.get(f"/monobank/monoaccounts/")
    if resp.status_code != 200:
        text = f"something went wrong try again or contast the support"
        await bot.send_message(message.chat.id, text)

    # [{
    #     "user": "552901111",
    #     "mono_token": "umedfPsJgqMZP5pHeFcy8Y6skmSJsadfasdfsadfasd",
    #     "active": true
    # }]
    for user in resp.json():
        if user.get("user") == str(message.from_user.id):
            has_account = True
            break
    else:
        available_commands += "\n /register - register your account"

    if has_account:
        available_commands += "\n /monojars - get you jars "
        available_commands += "\n /daily_report - manage daily transaction reports"
        available_commands += (
            "\n /family - manage family members to shared access to accounts"
        )

    await bot.send_message(message.chat.id, available_commands)


@dp.message_handler(state="*", commands=["monojars"])
async def monojars(message: types.Message):
    kb = (
        kbm.get_inline_keyboard()
        .row(kbm.get_mono_jars)
        .row(kbm.get_mono_jars_budget)
        .row(kbm.cancel_button)
    )
    await bot.send_message(
        message.chat.id,
        "pick your option",
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@dp.message_handler(state="*", commands=["daily_report"])
async def daily_report(message: types.Message):
    """Daily report management - enable/disable automated daily transaction reports."""

    # Check if user has daily report enabled
    user_id = str(message.from_user.id)
    is_enabled = False

    # Try to check if task exists (we can check via API if needed)
    # For now, we'll show both options

    enable_button = InlineKeyboardButton(
        "📊 Enable Daily Report", callback_data=f"enable_daily_report_{user_id}"
    )
    disable_button = InlineKeyboardButton(
        "🚫 Disable Daily Report", callback_data=f"disable_daily_report_{user_id}"
    )

    kb = (
        kbm.get_inline_keyboard()
        .row(enable_button)
        .row(disable_button)
        .row(kbm.cancel_button)
    )

    instruction_text = """📈 **Daily Transaction Report**

This automated report analyzes your daily MONO card transactions and helps you track your spending:

🔍 **What it does:**
• Shows ALL your spending transactions for the day
• Marks which spends are covered by income/positive transactions
• Lists leftover income not used for covering expenses
• Provides daily spending summary with coverage analysis

⏰ **When:** Every day at 21:00 (9 PM)

💡 **Why useful:**
• Track daily spending patterns
• See which expenses lack income coverage
• Monitor leftover funds
• Get insights for better budget management

Choose an option below:"""

    await bot.send_message(
        message.chat.id,
        instruction_text,
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.message_handler(state="*", commands=["family"])
async def family_menu(message: types.Message):
    """Family management: generate code, enter code, accept/decline invites."""
    gen_btn = InlineKeyboardButton(
        "👨‍👩‍👧 Generate my family code", callback_data="family_generate_code"
    )
    enter_btn = InlineKeyboardButton(
        "🔗 Enter code to invite", callback_data="family_enter_code"
    )
    kb = kbm.get_inline_keyboard().row(gen_btn).row(enter_btn).row(kbm.cancel_button)
    txt = (
        "Family linking options:\n\n"
        "- Generate a code and share it with your family member.\n"
        "- The other person enters the code to send you an invite.\n"
        "- You'll receive an Accept/Decline message."
    )
    await bot.send_message(message.chat.id, txt, reply_markup=kb)


@dp.callback_query_handler(lambda c: c.data == "family_generate_code")
async def family_generate_code(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    user_id = str(callback_query.from_user.id)
    resp = rm.post(f"/account/users/{user_id}/family_code/", {})
    if resp.status_code not in (200, 201):
        await bot.send_message(
            callback_query.message.chat.id, "Failed to generate code. Try again later."
        )
        return
    data = resp.json()
    code_val = data.get("code", "??????")
    expires_in = int(data.get("expires_in", 600))
    minutes = max(1, expires_in // 60)
    msg = (
        f"Your family code: {code_val}\n"
        f"Share this with the person who wants to link with you.\n"
        f"Expires in ~{minutes} min."
    )
    await bot.send_message(callback_query.message.chat.id, msg)


@dp.callback_query_handler(lambda c: c.data == "family_enter_code")
async def family_enter_code(callback_query: types.CallbackQuery):
    await reply_on_button(callback_query, InlineKeyboardButton("Enter code"), bot)
    state = dp.current_state(user=callback_query.from_user.id)
    await state.set_state(state=FamilyStates.code_enter)
    kb = kbm.get_inline_keyboard().row(kbm.cancel_button)
    await bot.send_message(
        callback_query.message.chat.id,
        "Send the family code you received:",
        reply_markup=kb,
    )


@dp.message_handler(state=FamilyStates.code_enter)
async def family_code_entered(message: types.Message):
    code = (message.text or "").strip().upper()
    state = dp.current_state(user=message.from_user.id)
    await state.reset_state()
    if not code or len(code) < 4:
        await bot.send_message(
            message.chat.id, "Invalid code. Use /family and try again."
        )
        return
    payload = {"inviter_tg_id": str(message.from_user.id), "code": code}
    resp = rm.post("/account/users/family_invite/proposal/", payload)
    if resp.status_code != 201:
        if resp.status_code == 404:
            await bot.send_message(
                message.chat.id, "Invalid or expired code. Ask them to regenerate."
            )
        elif resp.status_code == 400:
            await bot.send_message(
                message.chat.id, "Bad request. Ensure you pasted the correct code."
            )
        else:
            await bot.send_message(
                message.chat.id, f"Failed to send invite: {resp.status_code}"
            )
        return

    data = resp.json()
    invite_id = data.get("invite_id")
    member_tg_id = data.get("member_tg_id")
    inviter_name = (
        (message.from_user.full_name or "Someone")
        if hasattr(message.from_user, "full_name")
        else "Someone"
    )

    await bot.send_message(message.chat.id, "Invite sent. Waiting for confirmation.")

    # Try to notify the member with accept/decline buttons
    try:
        accept_btn = InlineKeyboardButton(
            "✅ Accept", callback_data=f"family_accept_{invite_id}"
        )
        decline_btn = InlineKeyboardButton(
            "❌ Decline", callback_data=f"family_decline_{invite_id}"
        )
        kb = kbm.get_inline_keyboard().row(accept_btn, decline_btn)
        member_msg = (
            f"You received a family link request from {inviter_name} (tg_id: {message.from_user.id}).\n"
            f"Do you want to link accounts as family members?"
        )
        await bot.send_message(int(member_tg_id), member_msg, reply_markup=kb)
    except Exception:
        # If we can't message the member, the inviter will still have to wait
        pass


@dp.callback_query_handler(
    lambda c: c.data.startswith("family_accept_")
    or c.data.startswith("family_decline_")
)
async def family_decision(callback_query: types.CallbackQuery):
    await bot.answer_callback_query(callback_query.id)
    is_accept = callback_query.data.startswith("family_accept_")
    invite_id = callback_query.data.split("_")[-1]
    decision = "accept" if is_accept else "decline"
    payload = {
        "invite_id": invite_id,
        "decision": decision,
        "actor_tg_id": str(callback_query.from_user.id),
    }

    # Remove buttons immediately to prevent multiple clicks
    try:
        await bot.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=None,
        )
    except Exception:
        pass

    resp = rm.post("/account/users/family_invite/decision/", payload)
    if resp.status_code != 200:
        await bot.send_message(
            callback_query.message.chat.id,
            f"Failed to process decision: {resp.status_code}",
        )
        return
    data = resp.json()
    inviter_tg_id = data.get("inviter_tg_id")
    member_tg_id = data.get("member_tg_id")
    status = data.get("status")

    # Notify actor
    if status == "accepted":
        await bot.send_message(
            callback_query.message.chat.id, "✅ Family link established."
        )
    else:
        await bot.send_message(callback_query.message.chat.id, "❌ Invite declined.")

    # Notify inviter
    try:
        if status == "accepted":
            await bot.send_message(
                int(inviter_tg_id),
                "✅ Your family invite was accepted. You are now linked.",
            )
        else:
            await bot.send_message(
                int(inviter_tg_id), "❌ Your family invite was declined."
            )
    except Exception:
        pass


@dp.callback_query_handler(lambda c: c.data.startswith("enable_daily_report_"))
async def enable_daily_report_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.data.replace("enable_daily_report_", "")
    await bot.answer_callback_query(callback_query.id)

    # Call API to enable daily report
    resp = rm.post("/monobank/daily-report-scheduler/", {"tg_id": user_id})

    if resp.status_code in [200, 201]:
        await bot.send_message(
            callback_query.message.chat.id,
            "✅ **Daily Report Enabled!**\n\n"
            "You will receive automated daily transaction reports every day at 21:00 (9 PM).\n\n"
            "The report will analyze your spending and show coverage by income transactions.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await bot.send_message(
            callback_query.message.chat.id,
            f"❌ **Failed to enable daily report**\n\n"
            f"Error: {resp.status_code}\n"
            f"Please try again later or contact support.",
            parse_mode=ParseMode.MARKDOWN,
        )


@dp.callback_query_handler(lambda c: c.data.startswith("disable_daily_report_"))
async def disable_daily_report_handler(callback_query: types.CallbackQuery):
    user_id = callback_query.data.replace("disable_daily_report_", "")
    await bot.answer_callback_query(callback_query.id)

    # Call API to disable daily report
    resp = rm.delete("/monobank/daily-report-scheduler/", {"tg_id": user_id})

    if resp.status_code == 200:
        await bot.send_message(
            callback_query.message.chat.id,
            "🚫 **Daily Report Disabled**\n\n"
            "You will no longer receive automated daily transaction reports.\n\n",
            parse_mode=ParseMode.MARKDOWN,
        )
    elif resp.status_code == 404:
        await bot.send_message(
            callback_query.message.chat.id,
            "ℹ️ **No Active Daily Report**\n\n"
            "You don't have an active daily report scheduled.\n\n"
            "Use the enable option if you want to start receiving daily reports.",
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await bot.send_message(
            callback_query.message.chat.id,
            f"❌ **Failed to disable daily report**\n\n"
            f"Error: {resp.status_code}\n"
            f"Please try again later or contact support.",
            parse_mode=ParseMode.MARKDOWN,
        )


@dp.callback_query_handler(
    lambda c: c.data in ["get_user_jars", "get_user_jars_budget"]
)
async def get_user_jars_combined(callback_query: types.CallbackQuery):
    is_budget = callback_query.data == "get_user_jars_budget"
    button = kbm.get_mono_jars_budget if is_budget else kbm.get_mono_jars
    await reply_on_button(callback_query, button, bot)
    url = f"/monobank/monojars/?users={callback_query.from_user.id}"
    if is_budget:
        url += "&is_budget=True&with_family=True"
    resp = rm.get(url)
    if resp.status_code != 200:
        txt = "Something went wrong. Try other commands or /help"
        await bot.send_message(callback_query.message.chat.id, txt)
        return

    data = resp.json()
    if len(data) == 0:
        txt = "No budget jars to display" if is_budget else "No jars to display"
        await bot.send_message(callback_query.message.chat.id, txt)
        return

    for jar in data:
        jar_obj = get_jar_data(jar)
        title = f"**__{jar_obj.title}__**"
        value = f"*{jar_obj.currency.flag} {jar_obj.balance / 100}{jar_obj.currency.name}*\n\[{jar_obj.owner_name}\]"
        # Toggle budget button reflects current state
        current_flag = 1 if getattr(jar_obj, "is_budget", False) else 0
        button_text = "Unset budget" if current_flag == 1 else "Set as budget"
        toggle_button = InlineKeyboardButton(
            button_text,
            callback_data=f"toggle_budget_{jar_obj.id}*{current_flag}",
        )
        months_button = InlineKeyboardButton(
            "📅 Available months", callback_data=f"jar_months_{jar_obj.id}"
        )
        chart_button = InlineKeyboardButton(
            "📊 Chart", callback_data=f"jar_chart_{jar_obj.id}"
        )
        kb = (
            kbm.get_inline_keyboard()
            .row(toggle_button, months_button)
            .row(chart_button)
        )
        await bot.send_message(
            callback_query.message.chat.id,
            f"{title}\n{value}".replace(".", "\\."),
            parse_mode=ParseMode.MARKDOWN_V2,
            reply_markup=kb,
        )


@dp.callback_query_handler(lambda c: c.data.startswith("jar_months_"))
async def jar_available_months_handler(callback_query: types.CallbackQuery):
    jar_id = callback_query.data.replace("jar_months_", "")
    # Fetch jar details for title and currency
    jar_resp = rm.get(f"/monobank/monojars/{jar_id}/")
    months_resp = rm.get(f"/monobank/monojars/{jar_id}/available-months/")

    if jar_resp.status_code != 200 or months_resp.status_code != 200:
        await bot.send_message(
            callback_query.message.chat.id,
            "Failed to fetch available months. Please try again later.",
        )
        return

    jar = jar_resp.json()
    jar_obj = get_jar_data(jar)
    months = months_resp.json()  # ["YYYY-MM-01", ...]

    if len(months) == 0:
        await bot.send_message(
            callback_query.message.chat.id,
            f"No transactions months for {jar_obj.title}".replace(".", "\\."),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return

    kb = kbm.get_inline_keyboard()
    # Add month buttons (show as YYYY-MM)
    for month_str in months:
        label = f"{month_str[:7]}"
        kb = kb.add(
            InlineKeyboardButton(
                f"📆 {label}",
                callback_data=f"jar_month_summary_{jar_obj.id}*{month_str}",
            )
        )

    header = f"**__{jar_obj.title}__**\nPick month:".replace(".", "\\.")
    await bot.send_message(
        callback_query.message.chat.id,
        header,
        parse_mode=ParseMode.MARKDOWN_V2,
        reply_markup=kb,
    )


@dp.callback_query_handler(
    lambda c: c.data.startswith("jar_chart_")
    and not c.data.startswith("jar_chart_period_")
)
async def jar_chart_options_handler(callback_query: types.CallbackQuery):
    jar_id = callback_query.data.replace("jar_chart_", "")
    await reply_on_button(callback_query, InlineKeyboardButton("Chart"), bot)
    jar_title = "Jar"
    try:
        jar_resp = rm.get(f"/monobank/monojars/{jar_id}/")
        if jar_resp.status_code == 200:
            jar_obj = get_jar_data(jar_resp.json())
            jar_title = jar_obj.title or jar_title
    except Exception:
        pass
    kb = (
        kbm.get_inline_keyboard()
        .row(
            InlineKeyboardButton(
                "📈 1 month", callback_data=f"jar_chart_period_{jar_id}*1m"
            ),
            InlineKeyboardButton(
                "📈 3 months", callback_data=f"jar_chart_period_{jar_id}*3m"
            ),
        )
        .row(
            InlineKeyboardButton(
                "📈 All time", callback_data=f"jar_chart_period_{jar_id}*all"
            )
        )
    )

    await bot.send_message(
        callback_query.message.chat.id,
        f"Pick period for chart [{jar_title}]",
        reply_markup=kb,
    )


def _compute_time_from(period_code: str) -> str | None:
    if period_code == "1m":
        dt = datetime.now() - timedelta(days=30)
    elif period_code == "3m":
        dt = datetime.now() - timedelta(days=90)
    else:
        return None
    return dt.strftime("%Y-%m-%d")


@dp.callback_query_handler(lambda c: c.data.startswith("jar_chart_period_"))
async def jar_chart_fetch_handler(callback_query: types.CallbackQuery):
    payload = callback_query.data.replace("jar_chart_period_", "")
    jar_id, period_code = payload.split("*")
    await bot.answer_callback_query(callback_query.id)

    time_from = _compute_time_from(period_code)
    endpoint = (
        f"/monobank/monojartransactions/?jars={jar_id}&fields=balance,formatted_time"
    )
    if time_from:
        endpoint += f"&time_from={time_from}"

    # Fetch transactions
    resp = rm.get(endpoint)
    if resp.status_code != 200:
        await bot.send_message(
            callback_query.message.chat.id,
            f"Failed to fetch transactions for chart: {resp.status_code}",
        )
        return

    data = resp.json()  # list of {balance, formatted_time}
    if not isinstance(data, list) or len(data) == 0:
        await bot.send_message(
            callback_query.message.chat.id, "No transactions to display"
        )
        return

    # Fetch jar details for title/currency
    jar_title = "Jar"
    currency_name = ""
    currency_symbol = ""
    try:
        jar_resp = rm.get(f"/monobank/monojars/{jar_id}/")
        if jar_resp.status_code == 200:
            jar_obj = get_jar_data(jar_resp.json())
            jar_title = jar_obj.title or jar_title
            currency_name = getattr(jar_obj.currency, "name", "") or ""
            currency_symbol = getattr(jar_obj.currency, "symbol", "") or ""
    except Exception:
        pass

    # Prepare data for plotting
    try:
        time_strings = [item.get("formatted_time", "") for item in data]
        y_values = [int(item.get("balance", 0)) / 100 for item in data]
    except Exception:
        await bot.send_message(
            callback_query.message.chat.id, "Unexpected data format for chart"
        )
        return

    # Parse times and compute month markers
    try:
        times = [datetime.strptime(ts, "%Y-%m-%d %H:%M:%S") for ts in time_strings]
    except Exception:
        times = []
        for ts in time_strings:
            try:
                times.append(datetime.fromisoformat(ts))
            except Exception:
                times.append(datetime.now())

    x_positions = list(range(len(times)))
    month_indices: list[int] = []
    month_labels: list[str] = []
    last_key: tuple[int, int] | None = None
    for idx, dt in enumerate(times):
        key = (dt.year, dt.month)
        if key != last_key:
            month_indices.append(idx)
            month_labels.append(dt.strftime("%b %Y"))
            last_key = key

    # Apply a modern style
    try:
        plt.style.use("seaborn-v0_8")
    except Exception:
        try:
            plt.style.use("seaborn")
        except Exception:
            plt.style.use("ggplot")

    # Plot chart with improved aesthetics
    fig, ax = plt.subplots(figsize=(12, 5))
    line_color = "#2E86DE"
    ax.plot(
        x_positions,
        y_values,
        color=line_color,
        marker="o",
        markersize=4,
        linewidth=2.0,
        markerfacecolor="#ffffff",
        markeredgecolor=line_color,
        markeredgewidth=1.25,
        antialiased=True,
    )
    ax.fill_between(x_positions, y_values, color=line_color, alpha=0.08)

    # X-axis: only month markers and vertical guide lines
    if month_indices:
        ax.set_xticks(month_indices)
        ax.set_xticklabels(month_labels, rotation=0, ha="center")
        for mi in month_indices:
            ax.axvline(
                x=mi,
                color="#95A5A6",
                linestyle=(0, (4, 6)),
                linewidth=0.8,
                alpha=0.3,
                zorder=0,
            )
    else:
        ax.set_xticks([])

    # Horizontal grid lines
    ax.grid(True, axis="y", linestyle=(0, (4, 6)), linewidth=0.8, alpha=0.35)

    # Clean up spines and ticks
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_alpha(0.5)
    ax.spines["bottom"].set_alpha(0.5)
    ax.tick_params(axis="x", length=0, labelsize=9)
    ax.tick_params(axis="y", labelsize=9)

    # Labels and title with jar name and currency
    y_label_suffix = f", {currency_name}" if currency_name else ""
    ax.set_ylabel(f"Balance{y_label_suffix}")
    ax.set_title(f"{jar_title} — Balance over time")

    # Format Y-axis as currency if symbol known
    if currency_symbol:
        ax.yaxis.set_major_formatter(
            mticker.StrMethodFormatter(f"{currency_symbol}{{x:,.2f}}")
        )

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)

    caption = "Chart period: " + (
        "1 month"
        if period_code == "1m"
        else ("3 months" if period_code == "3m" else "All time")
    )
    await bot.send_photo(
        callback_query.message.chat.id,
        photo=InputFile(buf, filename="jar_balance_chart.png"),
        caption=caption,
    )


@dp.callback_query_handler(lambda c: c.data.startswith("jar_month_summary_"))
async def jar_month_summary_handler(callback_query: types.CallbackQuery):
    payload = callback_query.data.replace("jar_month_summary_", "")
    jar_id, month_str = payload.split("*")

    # Fetch summary and jar details for formatting
    summary_resp = rm.get(
        f"/monobank/monojars/{jar_id}/month-summary/?month={month_str}"
    )
    jar_resp = rm.get(f"/monobank/monojars/{jar_id}/")

    if summary_resp.status_code != 200 or jar_resp.status_code != 200:
        await bot.send_message(
            callback_query.message.chat.id,
            "Failed to fetch month summary. Please try again later.",
        )
        return

    summary = summary_resp.json()
    jar = jar_resp.json()
    jar_obj = get_jar_data(jar)

    def fmt(amount: int) -> str:
        try:
            return f"{(amount or 0) / 100:.2f}"
        except Exception:
            return "0.00"

    start_balance = fmt(summary.get("start_balance", 0))
    budget = fmt(summary.get("budget", 0))
    end_balance = fmt(summary.get("end_balance", 0))
    spent = fmt(summary.get("spent", 0))

    text_msg = (
        f"📦 Jar: {jar_obj.title}\n"
        f"📅 Month: {month_str[:7]}\n"
        f"🔹 Start balance: 💰 {start_balance} {jar_obj.currency.name}\n"
        f"📈 Budget (max deposit): ➕ {budget} {jar_obj.currency.name}\n"
        f"🔻 End balance: 💰 {end_balance} {jar_obj.currency.name}\n"
        f"🧮 Spent: {spent} {jar_obj.currency.name}"
    )

    await bot.send_message(
        callback_query.message.chat.id,
        text_msg,
        parse_mode=ParseMode.MARKDOWN,
    )


@dp.callback_query_handler(lambda c: c.data.startswith("toggle_budget_"))
async def toggle_budget_handler(callback_query: types.CallbackQuery):
    jar_id = callback_query.data.replace("toggle_budget_", "").split("*")[0]
    current_flag = int(callback_query.data.replace("toggle_budget_", "").split("*")[1])
    new_flag = 1 - current_flag

    # Call API to set this jar as budget for the user
    resp = rm.patch(
        f"/monobank/monojars/{jar_id}/set_budget_status/", {"is_budget": bool(new_flag)}
    )

    if resp.status_code == 200:
        # Update the inline keyboard in place with the opposite action
        next_text = "Unset budget" if new_flag == 1 else "Set as budget"
        new_button = InlineKeyboardButton(
            next_text,
            callback_data=f"toggle_budget_{jar_id}*{new_flag}",
        )
        new_kb = kbm.get_inline_keyboard().add(new_button)
        await bot.edit_message_reply_markup(
            chat_id=callback_query.message.chat.id,
            message_id=callback_query.message.message_id,
            reply_markup=new_kb,
        )
        await bot.answer_callback_query(
            callback_query.id,
            text=("Set as budget ✅" if new_flag == 1 else "Unset budget ✅"),
            show_alert=False,
        )
    else:
        await bot.answer_callback_query(
            callback_query.id,
            text=f"Failed to toggle budget: {resp.status_code}",
            show_alert=True,
        )


# INFO COMMANDS
@dp.message_handler(state="*", commands=["register"])
async def register(message: types.Message):
    resp = rm.get(f"/account/users/{message.from_user.id}")
    if resp.status_code == 200:
        txt = "Looks like you are registered already. Try other commands or /help"
        await bot.send_message(message.chat.id, txt)
        return
    resp = text(
        "This button will create account with your telegram ID and name \+ generated password for access website\. "
        "Click here to start using MonoHelper"
    )
    kb = kbm.get_inline_keyboard().row(kbm.register_button, kbm.cancel_button)
    await bot.send_message(
        message.chat.id, resp, reply_markup=kb, parse_mode=ParseMode.MARKDOWN_V2
    )


@dp.message_handler(state="*", commands=["token_add"])
async def token_add(message: types.Message):
    # TODO: check if exists
    resp = text(
        "Follow the link to get monobank token\. Please copy it and come back to insert it\. \n"
        "Note: this token give read\-only permissions and can be revoked anytime by same link\. Surely, "
        "revoked token will let you use this service untill you replace it with valid one\."
    )
    kb = kbm.get_inline_keyboard().row(
        kbm.get_mono_token_button, kbm.add_mono_token_button, kbm.cancel_button
    )
    await bot.send_message(
        message.chat.id, resp, reply_markup=kb, parse_mode=ParseMode.MARKDOWN_V2
    )


@dp.message_handler(state="*", commands=["hello"])
async def hello(message: types.Message):
    text = "Test start"
    await bot.send_message(message.chat.id, text)


# # -- INFO COMMANDS

# # +++ MONOBANK Block

# # STANDARD COMMANDS


@dp.message_handler()
async def echo(message: types.Message):
    logging.info(
        f"Received a message with no handling scenario from {message.from_user}. Echo!"
    )
    await bot.send_message(
        message.chat.id,
        text("Something unknown:\n", code(message.text)),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    # TODO HANDLE BUTTONS


async def reply_on_button(
    callback_query: types.CallbackQuery, button: InlineKeyboardButton, bot: Bot
):
    await bot.answer_callback_query(callback_query.id)
    await bot.send_message(
        callback_query.from_user.id,
        text("picked:\n", code(f"{button.text}")),
        parse_mode=ParseMode.MARKDOWN,
    )
    await callback_query.message.delete_reply_markup()


@dp.callback_query_handler(lambda c: c.data == "register_monouser")
async def register_monouser(callback_query: types.CallbackQuery):
    await reply_on_button(callback_query, kbm.register_button, bot)
    password = generate_password(PASSWORD_LENGTH)
    username = (
        f"{callback_query.from_user.last_name} {callback_query.from_user.first_name}"
    )
    resp = rm.post(
        "/account/users/",
        {
            "tg_id": f"{callback_query.from_user.id}",
            "password": password,
            "name": username,
        },
    )
    if resp.status_code != 201:
        await bot.send_message(
            callback_query.message.chat.id,
            text("Something went wrong:\n", code(resp.text)),
            parse_mode=ParseMode.MARKDOWN_V2,
        )
        return
    response = f"||{password}||"
    await bot.send_message(
        callback_query.message.chat.id,
        text("login:\n", code(f"{callback_query.from_user.id}")),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await bot.send_message(
        callback_query.message.chat.id,
        text("name:\n", code(username)),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    await bot.send_message(
        callback_query.message.chat.id,
        text("password:\n", text(f"||{password}||")),
        parse_mode=ParseMode.MARKDOWN_V2,
    )
    txt = "Now you can add mono token to access your accounts. Press /token_add to continue"
    await bot.send_message(callback_query.message.chat.id, txt)


@dp.callback_query_handler(lambda c: c.data == "add_mono_token")
async def add_monotoken(callback_query: types.CallbackQuery):
    state = dp.current_state(user=callback_query.from_user.id)
    await state.set_state(state=MonotokenStates.token_enter)
    txt = "Send your token or cancel"
    await reply_on_button(callback_query, kbm.add_mono_token_button, bot)
    kb = kbm.get_inline_keyboard().row(kbm.cancel_button)
    await bot.send_message(
        callback_query.message.chat.id,
        txt,
        reply_markup=kb,
        parse_mode=ParseMode.MARKDOWN_V2,
    )


@dp.message_handler(state=MonotokenStates.token_enter)
async def token(message: types.Message):
    state = dp.current_state(user=message.from_user.id)
    await state.reset_state()
    resp = rm.post(
        "/monobank/monoaccounts/",
        {"user": f"{message.from_user.id}", "mono_token": message.text},
    )
    if resp.status_code != 201:
        await bot.send_message(message.chat.id, resp.text)
        await bot.send_message(
            message.chat.id, "Something went wrong! Try whole process again /token_add"
        )
        return

    await bot.send_message(
        message.chat.id,
        "Great! Now you can use service to track your monobank operations. Try /help",
    )


@dp.callback_query_handler(lambda c: c.data == "cancel")
async def cancel(callback_query: types.CallbackQuery):
    await reply_on_button(callback_query, kbm.cancel_button, bot)
    state = dp.current_state(user=callback_query.from_user.id)
    await state.reset_state()


async def on_startup(_: Dispatcher):
    # global driver
    pass


#  -- STANDARD COMMANDS

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    start_polling(dispatcher=dp, on_startup=on_startup)
