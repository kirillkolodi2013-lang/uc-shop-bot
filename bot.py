import logging
import json
import os
from datetime import datetime, timezone, timedelta
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── КОНФИГ ───────────────────────────────────────────────
MAIN_TOKEN      = "9213475176:AAGMSnJA1azPtWtOsvhbpcsor2haA-G-9rU"
NOTIFY_TOKEN    = "9092817274:AAGYFG2SmuZBKZMOPiCi-XZ6x4HFORpf_Us"
ADMIN_IDS       = [7479833106, 8839353200]
GROUP_ID        = -1003839648610

MSK = timezone(timedelta(hours=3))

# ─── ПРАЙСЫ ───────────────────────────────────────────────
UC_PRICES = {
    60:   {"rub": 85,   "tmt": 24},
    120:  {"rub": 168,  "tmt": 48},
    180:  {"rub": 255,  "tmt": 72},
    325:  {"rub": 410,  "tmt": 116},
    385:  {"rub": 493,  "tmt": 145},
    660:  {"rub": 813,  "tmt": 246},
    720:  {"rub": 892,  "tmt": 265},
    1320: {"rub": 1622, "tmt": 536},
    1800: {"rub": 2020, "tmt": 625},
}

# Сопровождение: базовые цены за карту 7
ESCORT_PRICES = {
    "bronze": {"rub": 100, "tmt": 20, "emoji": "🥉", "name": "Бронза"},
    "silver": {"rub": 130, "tmt": 30, "emoji": "🥈", "name": "Серебро"},
    "gold":   {"rub": 150, "tmt": 40, "emoji": "🥇", "name": "Золото"},
    "vip":    {"rub": 200, "tmt": 70, "emoji": "💎", "name": "VIP"},
}
ESCORT_MAP8_EXTRA  = {"rub": 20, "tmt": 5}
ESCORT_QUEUE_EXTRA = {"rub": 40, "tmt": 10}

ESCORT_DESC = {
    "bronze": (
        "🥉 *БРОНЗА*\n\n"
        "• Вынос 5+ млн метро валюты\n"
        "• В начале выдаём Full 6 + пластина + 2 подсумки с МК ВК\n"
        "• Вещи выдаём после сопровода\n"
        "• Если что-то выпадает — компенсируем и начинаем заново 😄"
    ),
    "silver": (
        "🥈 *СЕРЕБРО*\n\n"
        "• В начале выдаём Full 6 + платина + 2 подсумки с МК ВК\n"
        "• Вынос 10+ млн метро валюты\n"
        "• Вещи выдаём после сопровода\n"
        "• Компенсация при потере 😄"
    ),
    "gold": (
        "🥇 *ЗОЛОТО*\n\n"
        "• В начале выдаём Full 6 + пластина + 2 подсумки с МК ВК\n"
        "• Вынос 15+ млн метро валюты\n"
        "• Вещи выдаём после сопровода\n"
        "• Компенсация при потере 😄"
    ),
    "vip": (
        "💎 *VIP*\n\n"
        "• Сопровод БЕЗ ОЧЕРЕДИ!\n"
        "• Full 6 Золото + пластина + 2 подсумки с МК ВК + золотая пушка в подарок 🎁\n"
        "• Вынос 20+ млн метро валюты\n"
        "• Компенсация при потере (кроме золотых вещей)\n\n"
        "❗ Если надели золотую вещь и её сняли — выдаём обычный сет\n"
        "❗❗ Если руините сопровод и не слушаетесь — заканчиваем без возврата средств"
    ),
}

# Metro-Shop
SHOP_ITEMS = {
    "helmet":  {"name": "⛑ Шлем",         "rub": [6,7,8],   "tmt": [2,2.5,3]},
    "armor":   {"name": "🦺 Броня+ткань",  "rub": [6,7,8],   "tmt": [2,2.5,3]},
    "bag":     {"name": "🎒 Рюкзак",       "rub": [6,6,6],   "tmt": [2,2,2]},
    "mk14":    {"name": "🔫 МК14+обвесы",  "rub": [6,8,7],   "tmt": [2,3,2.5]},
    "guns":    {"name": "💥 Остальные пушки","rub": [6,7,8],  "tmt": [2,3,2.5]},
    "full6":   {"name": "📦 Фул 6 (без МК)","rub": [15,18,20],"tmt": [5,6,7]},
    "full6mk": {"name": "📦 Фул 6 с МК ВК","rub": [20,23,25],"tmt": [7,8,9]},
}
SHOP_MODES = ["Обычное", "КБ", "СФ"]

# Реквизиты
REQUISITES = {
    "rub": "🇷🇺 Переведите на карту Сбербанка:\n`2202 2089 9525 6659`",
    "tmt": "🇹🇲 Переведите на номер:\n`+993 61230984`",
}

# ─── ХРАНИЛИЩЕ ────────────────────────────────────────────
STATS_FILE = "stats.json"

def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE) as f:
            return json.load(f)
    return {}

def save_stats(data):
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# order_id -> order info
orders = {}
order_counter = [1000]

# group_msg_id -> {order_id, takers: [user_id,...], taker_names:[...]}
group_orders = {}

# ─── СОСТОЯНИЯ ────────────────────────────────────────────
(
    STATE_MAIN,
    STATE_UC_CURRENCY, STATE_UC_AMOUNT, STATE_UC_PAYMENT, STATE_UC_SCREENSHOT,
    STATE_ESC_TIER, STATE_ESC_INFO, STATE_ESC_MAP, STATE_ESC_QUEUE,
    STATE_ESC_CURRENCY, STATE_ESC_PAYMENT, STATE_ESC_PUBGID, STATE_ESC_SCREENSHOT,
    STATE_SHOP_CURRENCY, STATE_SHOP_ITEM, STATE_SHOP_MODE,
    STATE_SHOP_PAYMENT, STATE_SHOP_PUBGID, STATE_SHOP_SCREENSHOT,
    STATE_ADMIN_CODE,
) = range(20)

# ─── ХЕЛПЕРЫ ──────────────────────────────────────────────
def new_order_id():
    order_counter[0] += 1
    return order_counter[0]

def currency_label(cur):
    return "🇷🇺 Рубли (₽)" if cur == "rub" else "🇹🇲 Манаты (TMT)"

def amount_label(cur, amount):
    return f"{amount}₽" if cur == "rub" else f"{amount} TMT"

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 UC", callback_data="menu_uc"),
         InlineKeyboardButton("⚔️ Сопровождение", callback_data="menu_escort")],
        [InlineKeyboardButton("🛒 Metro-Shop", callback_data="menu_shop")],
    ])

def currency_keyboard(prefix):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Рубли (₽)", callback_data=f"{prefix}_rub"),
         InlineKeyboardButton("🇹🇲 Манаты (TMT)", callback_data=f"{prefix}_tmt")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_main")],
    ])

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, edit=False):
    text = (
        "🎮 *Добро пожаловать в UC Shop!*\n\n"
        "Выберите раздел:"
    )
    kb = main_menu_keyboard()
    if edit:
        await update.callback_query.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        msg = update.message or (update.callback_query.message if update.callback_query else None)
        if msg:
            await msg.reply_text(text, reply_markup=kb, parse_mode="Markdown")

# ─── СТАРТ ────────────────────────────────────────────────
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    user = update.message.from_user
    welcome = (
        f"👋 Привет, *{user.first_name}*!\n\n"
        "🎮 Добро пожаловать в *UC Shop* — твой надёжный магазин для PUBG Mobile!\n\n"
        "У нас ты можешь:\n"
        "💎 Купить *UC* по выгодным ценам\n"
        "⚔️ Заказать *сопровождение* с профи-игроками\n"
        "🛒 Приобрести снаряжение в *Metro-Shop*\n\n"
        "Оплата: 🇷🇺 Рубли и 🇹🇲 Манаты\n"
        "⚡️ Быстро • Надёжно • Выгодно\n\n"
        "Выбирай раздел и поехали! 👇"
    )
    await update.message.reply_text(welcome, parse_mode="Markdown")
    await send_main_menu(update, context)


async def cmd_start_notifier(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✅ Бот успешно подключён! Уведомления о заказах будут приходить сюда.")

# ─── ГЛАВНОЕ МЕНЮ ─────────────────────────────────────────
async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    await q.answer()
    data = q.data

    # ── Назад в главное меню
    if data == "back_main":
        context.user_data.clear()
        await send_main_menu(update, context, edit=True)
        return

    # ═══════════════════════════════════════
    # UC
    # ═══════════════════════════════════════
    if data == "menu_uc":
        await q.edit_message_text(
            "🎮 *UC — выберите валюту:*",
            reply_markup=currency_keyboard("uc_cur"),
            parse_mode="Markdown"
        )
        return

    if data.startswith("uc_cur_"):
        cur = data.split("_")[2]
        context.user_data["uc_currency"] = cur
        rows = []
        items = list(UC_PRICES.items())
        for i in range(0, len(items), 2):
            row = []
            for uc, p in items[i:i+2]:
                price = p[cur]
                label = f"{uc} UC — {amount_label(cur, price)}"
                row.append(InlineKeyboardButton(label, callback_data=f"uc_amt_{uc}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data="menu_uc")])
        await q.edit_message_text(
            f"🎮 *UC | {currency_label(cur)}*\n\nВыберите количество:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="Markdown"
        )
        return

    if data.startswith("uc_amt_"):
        uc = int(data.split("_")[2])
        cur = context.user_data.get("uc_currency", "rub")
        price = UC_PRICES[uc][cur]
        context.user_data["uc_amount"] = uc
        context.user_data["uc_price"] = price
        req = REQUISITES[cur]
        text = (
            f"🎮 *{uc} UC* | {currency_label(cur)}\n"
            f"💰 К оплате: *{amount_label(cur, price)}*\n\n"
            f"{req}\n\n"
            "После оплаты нажмите кнопку ниже и пришлите скриншот чека."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Я оплатил", callback_data="uc_paid")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"uc_cur_{cur}")],
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    if data == "uc_paid":
        context.user_data["awaiting"] = "uc_screenshot"
        await q.edit_message_text(
            "📸 Пришлите скриншот оплаты:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data=f"uc_amt_{context.user_data.get('uc_amount', 0)}")]
            ])
        )
        return

    # ═══════════════════════════════════════
    # СОПРОВОЖДЕНИЕ
    # ═══════════════════════════════════════
    if data == "menu_escort":
        rows = []
        tiers = list(ESCORT_PRICES.items())
        for i in range(0, len(tiers), 2):
            row = []
            for key, p in tiers[i:i+2]:
                row.append(InlineKeyboardButton(f"{p['emoji']} {p['name']}", callback_data=f"esc_tier_{key}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data="back_main")])
        await q.edit_message_text(
            "⚔️ *Сопровождение — выберите тариф:*",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="Markdown"
        )
        return

    if data.startswith("esc_tier_"):
        tier = data.split("_")[2]
        context.user_data["esc_tier"] = tier
        desc = ESCORT_DESC[tier]
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Выбрать", callback_data=f"esc_map_{tier}")],
            [InlineKeyboardButton("🔙 Назад", callback_data="menu_escort")],
        ])
        await q.edit_message_text(desc, reply_markup=kb, parse_mode="Markdown")
        return

    if data.startswith("esc_map_"):
        tier = data.split("_")[2]
        context.user_data["esc_tier"] = tier
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🗺 Карта 7", callback_data="esc_m_7"),
             InlineKeyboardButton("🗺 Карта 8", callback_data="esc_m_8")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"esc_tier_{tier}")],
        ])
        await q.edit_message_text(
            "🗺 *Выберите карту:*",
            reply_markup=kb,
            parse_mode="Markdown"
        )
        return

    if data.startswith("esc_m_"):
        map_num = int(data.split("_")[2])
        context.user_data["esc_map"] = map_num
        tier = context.user_data.get("esc_tier")
        p = ESCORT_PRICES[tier]
        # VIP всегда без очереди
        if tier == "vip":
            context.user_data["esc_queue"] = True
            await _show_esc_currency(q, context)
        else:
            extra_rub = ESCORT_MAP8_EXTRA["rub"] if map_num == 8 else 0
            extra_tmt = ESCORT_MAP8_EXTRA["tmt"] if map_num == 8 else 0
            base_rub = p["rub"] + extra_rub
            base_tmt = p["tmt"] + extra_tmt
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"➕ Без очереди (+40₽ / +10 TMT)",
                    callback_data="esc_queue_yes"
                )],
                [InlineKeyboardButton("➡️ Продолжить без", callback_data="esc_queue_no")],
                [InlineKeyboardButton("🔙 Назад", callback_data=f"esc_map_{tier}")],
            ])
            await q.edit_message_text(
                f"⚔️ *{p['emoji']} {p['name']} | Карта {map_num}*\n\n"
                f"💰 Цена: *{base_rub}₽ / {base_tmt} TMT*\n\n"
                "Добавить \"без очереди\"?",
                reply_markup=kb,
                parse_mode="Markdown"
            )
        return

    if data in ("esc_queue_yes", "esc_queue_no"):
        context.user_data["esc_queue"] = (data == "esc_queue_yes")
        await _show_esc_currency(q, context)
        return

    if data.startswith("esc_cur_"):
        cur = data.split("_")[2]
        context.user_data["esc_currency"] = cur
        context.user_data["awaiting"] = "esc_pubgid"
        await q.edit_message_text(
            "🎮 Введите ваш *PUBG ID*:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data=f"esc_m_{context.user_data.get('esc_map', 7)}")]
            ]),
            parse_mode="Markdown"
        )
        return

    # ═══════════════════════════════════════
    # METRO-SHOP
    # ═══════════════════════════════════════
    if data == "menu_shop":
        await q.edit_message_text(
            "🛒 *Metro-Shop — выберите валюту:*",
            reply_markup=currency_keyboard("shop_cur"),
            parse_mode="Markdown"
        )
        return

    if data.startswith("shop_cur_"):
        cur = data.split("_")[2]
        context.user_data["shop_currency"] = cur
        rows = []
        items = list(SHOP_ITEMS.items())
        for i in range(0, len(items), 2):
            row = []
            for key, item in items[i:i+2]:
                row.append(InlineKeyboardButton(item["name"], callback_data=f"shop_item_{key}"))
            rows.append(row)
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data="menu_shop")])
        await q.edit_message_text(
            f"🛒 *Metro-Shop | {currency_label(cur)}*\n\nВыберите товар:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="Markdown"
        )
        return

    if data.startswith("shop_item_"):
        key = data.replace("shop_item_", "")
        context.user_data["shop_item"] = key
        cur = context.user_data.get("shop_currency", "rub")
        item = SHOP_ITEMS[key]
        rows = []
        for i, mode in enumerate(SHOP_MODES):
            price = item[cur][i]
            rows.append([InlineKeyboardButton(
                f"{mode} — {amount_label(cur, price)}",
                callback_data=f"shop_mode_{i}"
            )])
        rows.append([InlineKeyboardButton("🔙 Назад", callback_data=f"shop_cur_{cur}")])
        await q.edit_message_text(
            f"🛒 *{item['name']}*\n\nВыберите вариант:",
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode="Markdown"
        )
        return

    if data.startswith("shop_mode_"):
        mode_idx = int(data.split("_")[2])
        context.user_data["shop_mode"] = mode_idx
        cur = context.user_data.get("shop_currency", "rub")
        key = context.user_data.get("shop_item")
        item = SHOP_ITEMS[key]
        price = item[cur][mode_idx]
        context.user_data["shop_price"] = price
        req = REQUISITES[cur]
        text = (
            f"🛒 *{item['name']} | {SHOP_MODES[mode_idx]}*\n"
            f"💰 К оплате: *{amount_label(cur, price)}*\n\n"
            f"{req}\n\n"
            "После оплаты нажмите кнопку ниже и пришлите скриншот."
        )
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Я оплатил", callback_data="shop_paid")],
            [InlineKeyboardButton("🔙 Назад", callback_data=f"shop_item_{key}")],
        ])
        await q.edit_message_text(text, reply_markup=kb, parse_mode="Markdown")
        return

    if data == "shop_paid":
        context.user_data["awaiting"] = "shop_pubgid"
        await q.edit_message_text(
            "🎮 Введите ваш *PUBG ID*:",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data=f"shop_mode_{context.user_data.get('shop_mode', 0)}")]
            ]),
            parse_mode="Markdown"
        )
        return

    # ═══════════════════════════════════════
    # ДЕЙСТВИЯ АДМИНА
    # ═══════════════════════════════════════
    if data.startswith("admin_confirm_"):
        order_id = int(data.split("_")[2])
        order = orders.get(order_id)
        if not order:
            await q.edit_message_text("❌ Заказ не найден.")
            return
        if order.get("confirmed"):
            await q.answer("Заказ уже обработан!", show_alert=True)
            return
        order["confirmed"] = True
        order["confirmed_by"] = q.from_user.id
        admin_name = q.from_user.username or q.from_user.first_name

        if order["type"] == "uc":
            # Просим код UC
            context.user_data[f"pending_code_{order_id}"] = True
            await q.edit_message_text(
                f"✅ Подтверждено — @{admin_name}\n\n"
                f"Введите код UC для заказа #{order_id}:",
                reply_markup=None
            )
            context.user_data["awaiting_code_order"] = order_id
        else:
            # Сопровождение или товар — отправляем в группу
            await q.edit_message_text(
                f"✅ Оплата подтверждена — @{admin_name}\n\n"
                f"Заказ #{order_id} отправлен в группу.",
                reply_markup=None
            )
            await _send_to_group(context, order_id, order)
        return

    if data.startswith("admin_decline_"):
        order_id = int(data.split("_")[2])
        order = orders.get(order_id)
        if not order:
            await q.edit_message_text("❌ Заказ не найден.")
            return
        if order.get("confirmed"):
            await q.answer("Заказ уже обработан!", show_alert=True)
            return
        order["confirmed"] = False
        admin_name = q.from_user.username or q.from_user.first_name
        await q.edit_message_text(
            f"❌ Оплата отклонена — @{admin_name}\n\nЗаказ #{order_id}",
            reply_markup=None
        )
        # Уведомляем покупателя
        try:
            await context.bot.send_message(
                order["user_id"],
                "❌ Оплата не подтверждена. Проверьте скриншот и попробуйте снова или обратитесь к администратору."
            )
        except Exception:
            pass
        return

    # Взяться за заказ (группа)
    if data.startswith("take_order_"):
        order_id = int(data.split("_")[2])
        order = orders.get(order_id)
        if not order:
            await q.answer("Заказ не найден!", show_alert=True)
            return

        user_id = q.from_user.id
        user_name = q.from_user.username or q.from_user.first_name
        takers = order.get("takers", [])
        taker_names = order.get("taker_names", [])
        max_takers = 3 if order["type"] == "escort" else 1

        if order.get("completed"):
            await q.answer("Заказ уже завершён!", show_alert=True)
            return
        if user_id in takers:
            await q.answer("Вы уже взялись за этот заказ!", show_alert=True)
            return
        if len(takers) >= max_takers:
            await q.answer("Мест больше нет!", show_alert=True)
            return

        takers.append(user_id)
        taker_names.append(f"@{user_name}")
        order["takers"] = takers
        order["taker_names"] = taker_names

        await _update_group_message(context, order_id, order, q.message)
        await q.answer("✅ Вы взялись за заказ!")
        return

    # Завершить заказ (только админ)
    if data.startswith("complete_order_"):
        order_id = int(data.split("_")[2])
        if q.from_user.id not in ADMIN_IDS:
            await q.answer("❌ Только администратор может завершить заказ!", show_alert=True)
            return
        order = orders.get(order_id)
        if not order:
            await q.answer("Заказ не найден!", show_alert=True)
            return
        if order.get("completed"):
            await q.answer("Заказ уже завершён!", show_alert=True)
            return

        order["completed"] = True
        order["completed_at"] = datetime.now(MSK).isoformat()
        admin_name = q.from_user.username or q.from_user.first_name

        # Сохраняем в статистику
        _record_stat(order)

        await _update_group_message(context, order_id, order, q.message, completed=True, admin_name=admin_name)
        await q.answer("✅ Заказ завершён!")

        # Уведомляем покупателя
        try:
            await context.bot.send_message(
                order["user_id"],
                f"✅ Ваш заказ #{order_id} выполнен! Спасибо за покупку 🎮"
            )
        except Exception:
            pass
        return


async def _show_esc_currency(q, context):
    tier = context.user_data.get("esc_tier")
    map_num = context.user_data.get("esc_map", 7)
    queue = context.user_data.get("esc_queue", False)
    p = ESCORT_PRICES[tier]

    extra_map_rub = ESCORT_MAP8_EXTRA["rub"] if map_num == 8 else 0
    extra_map_tmt = ESCORT_MAP8_EXTRA["tmt"] if map_num == 8 else 0
    extra_q_rub = ESCORT_QUEUE_EXTRA["rub"] if queue else 0
    extra_q_tmt = ESCORT_QUEUE_EXTRA["tmt"] if queue else 0

    total_rub = p["rub"] + extra_map_rub + extra_q_rub
    total_tmt = p["tmt"] + extra_map_tmt + extra_q_tmt

    context.user_data["esc_price_rub"] = total_rub
    context.user_data["esc_price_tmt"] = total_tmt

    queue_str = " + Без очереди" if queue else ""
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🇷🇺 Рубли (₽)", callback_data="esc_cur_rub"),
         InlineKeyboardButton("🇹🇲 Манаты (TMT)", callback_data="esc_cur_tmt")],
        [InlineKeyboardButton("🔙 Назад", callback_data=f"esc_m_{map_num}")],
    ])
    await q.edit_message_text(
        f"⚔️ *{p['emoji']} {p['name']} | Карта {map_num}{queue_str}*\n\n"
        f"💰 Рубли: *{total_rub}₽*\n"
        f"💰 Манаты: *{total_tmt} TMT*\n\n"
        "Выберите валюту оплаты:",
        reply_markup=kb,
        parse_mode="Markdown"
    )


async def _send_to_group(context, order_id, order):
    otype = order["type"]
    user = order.get("username", "неизвестен")
    uid = order.get("user_id")
    pubg_id = order.get("pubg_id", "—")
    cur = order.get("currency", "rub")
    max_takers = 3 if otype == "escort" else 1

    if otype == "escort":
        tier_key = order.get("tier")
        p = ESCORT_PRICES[tier_key]
        map_num = order.get("map", 7)
        queue = order.get("queue", False)
        price = order.get("price", 0)
        queue_str = " + Без очереди" if queue else ""
        text = (
            f"⚔️ *Новый заказ на сопровождение* #{order_id}\n\n"
            f"👤 @{user} (ID: {uid})\n"
            f"🎮 PUBG ID: `{pubg_id}`\n"
            f"🏆 Тариф: {p['emoji']} {p['name']}\n"
            f"🗺 Карта: {map_num}{queue_str}\n"
            f"💰 Оплачено: {amount_label(cur, price)}\n\n"
            f"👥 Взялись (0/{max_takers}):"
        )
    else:
        item_key = order.get("item")
        item = SHOP_ITEMS.get(item_key, {})
        mode_idx = order.get("mode_idx", 0)
        price = order.get("price", 0)
        text = (
            f"🛒 *Новый заказ Metro-Shop* #{order_id}\n\n"
            f"👤 @{user} (ID: {uid})\n"
            f"🎮 PUBG ID: `{pubg_id}`\n"
            f"📦 Товар: {item.get('name','—')} | {SHOP_MODES[mode_idx]}\n"
            f"💰 Оплачено: {amount_label(cur, price)}\n\n"
            f"👥 Взялись (0/{max_takers}):"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"✋ Взяться за заказ (0/{max_takers})", callback_data=f"take_order_{order_id}")],
        [InlineKeyboardButton("✅ Завершить заказ", callback_data=f"complete_order_{order_id}")],
    ])
    order["takers"] = []
    order["taker_names"] = []

    notify = notify_bot_app.bot if notify_bot_app else context.bot
    msg = await notify.send_message(GROUP_ID, text, reply_markup=kb, parse_mode="Markdown")
    order["group_msg_id"] = msg.message_id


async def _update_group_message(context, order_id, order, message, completed=False, admin_name=None):
    otype = order["type"]
    taker_names = order.get("taker_names", [])
    max_takers = 3 if otype == "escort" else 1
    cur = order.get("currency", "rub")

    if otype == "escort":
        tier_key = order.get("tier")
        p = ESCORT_PRICES[tier_key]
        map_num = order.get("map", 7)
        queue = order.get("queue", False)
        price = order.get("price", 0)
        queue_str = " + Без очереди" if queue else ""
        uid = order.get("user_id")
        user = order.get("username", "неизвестен")
        pubg_id = order.get("pubg_id", "—")
        base_text = (
            f"⚔️ *Заказ на сопровождение* #{order_id}\n\n"
            f"👤 @{user} (ID: {uid})\n"
            f"🎮 PUBG ID: `{pubg_id}`\n"
            f"🏆 Тариф: {p['emoji']} {p['name']}\n"
            f"🗺 Карта: {map_num}{queue_str}\n"
            f"💰 Оплачено: {amount_label(cur, price)}\n\n"
        )
    else:
        item_key = order.get("item")
        item = SHOP_ITEMS.get(item_key, {})
        mode_idx = order.get("mode_idx", 0)
        price = order.get("price", 0)
        uid = order.get("user_id")
        user = order.get("username", "неизвестен")
        pubg_id = order.get("pubg_id", "—")
        base_text = (
            f"🛒 *Заказ Metro-Shop* #{order_id}\n\n"
            f"👤 @{user} (ID: {uid})\n"
            f"🎮 PUBG ID: `{pubg_id}`\n"
            f"📦 Товар: {item.get('name','—')} | {SHOP_MODES[mode_idx]}\n"
            f"💰 Оплачено: {amount_label(cur, price)}\n\n"
        )

    if completed:
        takers_str = ", ".join(taker_names) if taker_names else "—"
        text = base_text + f"✅ *Заказ завершён* — @{admin_name}\n👥 Выполнили: {takers_str}"
        kb = None
    else:
        count = len(taker_names)
        takers_str = ", ".join(taker_names) if taker_names else "пока никто"
        text = base_text + f"👥 Взялись ({count}/{max_takers}): {takers_str}"
        if count >= max_takers:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Завершить заказ", callback_data=f"complete_order_{order_id}")],
            ])
        else:
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(f"✋ Взяться ({count}/{max_takers})", callback_data=f"take_order_{order_id}")],
                [InlineKeyboardButton("✅ Завершить заказ", callback_data=f"complete_order_{order_id}")],
            ])

    try:
        await message.edit_text(text, reply_markup=kb, parse_mode="Markdown")
    except Exception:
        pass


def _record_stat(order):
    stats = load_stats()
    otype = order["type"]
    taker_names = order.get("taker_names", [])
    completed_at = order.get("completed_at", "")

    if otype == "escort":
        tier_key = order.get("tier")
        p = ESCORT_PRICES[tier_key]
        label = f"{p['emoji']} {p['name']}"
    else:
        item_key = order.get("item")
        item = SHOP_ITEMS.get(item_key, {})
        mode_idx = order.get("mode_idx", 0)
        label = f"{item.get('name','—')} {SHOP_MODES[mode_idx]}"

    for name in taker_names:
        if name not in stats:
            stats[name] = []
        stats[name].append({"type": label, "at": completed_at})

    save_stats(stats)


# ─── СООБЩЕНИЯ (скриншоты, ID) ────────────────────────────
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    awaiting = context.user_data.get("awaiting")
    code_order = context.user_data.get("awaiting_code_order")

    # Код UC от админа
    if code_order and update.message.text:
        order_id = code_order
        order = orders.get(order_id)
        if order and update.message.from_user.id in ADMIN_IDS:
            code = update.message.text.strip()
            context.user_data.pop("awaiting_code_order", None)
            try:
                await context.bot.send_message(
                    order["user_id"],
                    f"✅ *Оплата принята!*\n\n"
                    f"🎮 Ваш код UC:\n`{code}`\n\n"
                    f"Спасибо за покупку! 🎉",
                    parse_mode="Markdown"
                )
                await update.message.reply_text(f"✅ Код отправлен покупателю (заказ #{order_id})")
            except Exception as e:
                await update.message.reply_text(f"❌ Ошибка отправки: {e}")
        return

    if not awaiting:
        return

    # UC скриншот
    if awaiting == "uc_screenshot":
        if not update.message.photo:
            await update.message.reply_text("📸 Пожалуйста, пришлите именно скриншот (фото).")
            return
        context.user_data.pop("awaiting")
        user = update.message.from_user
        uc = context.user_data.get("uc_amount")
        cur = context.user_data.get("uc_currency")
        price = context.user_data.get("uc_price")
        order_id = new_order_id()
        orders[order_id] = {
            "type": "uc",
            "user_id": user.id,
            "username": user.username or user.first_name,
            "uc": uc, "currency": cur, "price": price,
            "photo_id": update.message.photo[-1].file_id,
            "confirmed": False,
        }
        await update.message.reply_text(
            "⏳ Ваш заказ принят! Ожидайте подтверждения.",
            reply_markup=main_menu_keyboard()
        )
        await _notify_admins(context, order_id, orders[order_id], update.message.photo[-1].file_id)
        return

    # Сопровождение — PUBG ID
    if awaiting == "esc_pubgid":
        pubg_id = update.message.text.strip()
        if not pubg_id.isdigit():
            await update.message.reply_text("❌ ID должен содержать только цифры. Попробуйте снова:")
            return
        context.user_data["esc_pubgid"] = pubg_id
        context.user_data["awaiting"] = "esc_screenshot"
        cur = context.user_data.get("esc_currency", "rub")
        price = context.user_data.get(f"esc_price_{cur}", 0)
        req = REQUISITES[cur]
        await update.message.reply_text(
            f"💰 К оплате: *{amount_label(cur, price)}*\n\n{req}\n\nПосле оплаты пришлите скриншот чека.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data=f"esc_cur_{cur}")]
            ]),
            parse_mode="Markdown"
        )
        return

    # Сопровождение — скриншот
    if awaiting == "esc_screenshot":
        if not update.message.photo:
            await update.message.reply_text("📸 Пришлите скриншот оплаты (фото).")
            return
        context.user_data.pop("awaiting")
        user = update.message.from_user
        tier = context.user_data.get("esc_tier")
        map_num = context.user_data.get("esc_map", 7)
        queue = context.user_data.get("esc_queue", False)
        cur = context.user_data.get("esc_currency", "rub")
        price = context.user_data.get(f"esc_price_{cur}", 0)
        pubg_id = context.user_data.get("esc_pubgid", "—")
        order_id = new_order_id()
        orders[order_id] = {
            "type": "escort",
            "user_id": user.id,
            "username": user.username or user.first_name,
            "tier": tier, "map": map_num, "queue": queue,
            "currency": cur, "price": price, "pubg_id": pubg_id,
            "photo_id": update.message.photo[-1].file_id,
            "confirmed": False,
        }
        await update.message.reply_text(
            "⏳ Заказ принят! Ожидайте подтверждения оплаты.",
            reply_markup=main_menu_keyboard()
        )
        await _notify_admins(context, order_id, orders[order_id], update.message.photo[-1].file_id)
        return

    # Магазин — PUBG ID
    if awaiting == "shop_pubgid":
        pubg_id = update.message.text.strip()
        if not pubg_id.isdigit():
            await update.message.reply_text("❌ ID должен содержать только цифры. Попробуйте снова:")
            return
        context.user_data["shop_pubgid"] = pubg_id
        context.user_data["awaiting"] = "shop_screenshot"
        cur = context.user_data.get("shop_currency", "rub")
        price = context.user_data.get("shop_price", 0)
        req = REQUISITES[cur]
        await update.message.reply_text(
            f"💰 К оплате: *{amount_label(cur, price)}*\n\n{req}\n\nПосле оплаты пришлите скриншот чека.",
            parse_mode="Markdown"
        )
        return

    # Магазин — скриншот
    if awaiting == "shop_screenshot":
        if not update.message.photo:
            await update.message.reply_text("📸 Пришлите скриншот оплаты (фото).")
            return
        context.user_data.pop("awaiting")
        user = update.message.from_user
        item_key = context.user_data.get("shop_item")
        mode_idx = context.user_data.get("shop_mode", 0)
        cur = context.user_data.get("shop_currency", "rub")
        price = context.user_data.get("shop_price", 0)
        pubg_id = context.user_data.get("shop_pubgid", "—")
        order_id = new_order_id()
        orders[order_id] = {
            "type": "shop",
            "user_id": user.id,
            "username": user.username or user.first_name,
            "item": item_key, "mode_idx": mode_idx,
            "currency": cur, "price": price, "pubg_id": pubg_id,
            "photo_id": update.message.photo[-1].file_id,
            "confirmed": False,
        }
        await update.message.reply_text(
            "⏳ Заказ принят! Ожидайте подтверждения оплаты.",
            reply_markup=main_menu_keyboard()
        )
        await _notify_admins(context, order_id, orders[order_id], update.message.photo[-1].file_id)
        return


async def _notify_admins(context, order_id, order, photo_id):
    bot = notify_bot_app.bot if notify_bot_app else context.bot
    otype = order["type"]
    user = order.get("username", "неизвестен")
    uid = order.get("user_id")
    cur = order.get("currency", "rub")

    if otype == "uc":
        uc = order.get("uc")
        price = order.get("price")
        text = (
            f"🆕 *Новый заказ UC* #{order_id}\n\n"
            f"👤 @{user} (ID: `{uid}`)\n"
            f"🎮 {uc} UC\n"
            f"💰 {amount_label(cur, price)}"
        )
    elif otype == "escort":
        tier_key = order.get("tier")
        p = ESCORT_PRICES[tier_key]
        map_num = order.get("map", 7)
        queue = order.get("queue", False)
        price = order.get("price", 0)
        pubg_id = order.get("pubg_id", "—")
        queue_str = " + Без очереди" if queue else ""
        text = (
            f"🆕 *Новый заказ Сопровождение* #{order_id}\n\n"
            f"👤 @{user} (ID: `{uid}`)\n"
            f"🎮 PUBG ID: `{pubg_id}`\n"
            f"🏆 {p['emoji']} {p['name']} | Карта {map_num}{queue_str}\n"
            f"💰 {amount_label(cur, price)}"
        )
    else:
        item_key = order.get("item")
        item = SHOP_ITEMS.get(item_key, {})
        mode_idx = order.get("mode_idx", 0)
        price = order.get("price", 0)
        pubg_id = order.get("pubg_id", "—")
        text = (
            f"🆕 *Новый заказ Metro-Shop* #{order_id}\n\n"
            f"👤 @{user} (ID: `{uid}`)\n"
            f"🎮 PUBG ID: `{pubg_id}`\n"
            f"📦 {item.get('name','—')} | {SHOP_MODES[mode_idx]}\n"
            f"💰 {amount_label(cur, price)}"
        )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Оплата пришла", callback_data=f"admin_confirm_{order_id}"),
         InlineKeyboardButton("❌ Не пришла", callback_data=f"admin_decline_{order_id}")],
    ])

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_photo(
                chat_id=admin_id,
                photo=photo_id,
                caption=text,
                reply_markup=kb,
                parse_mode="Markdown"
            )
            logger.info(f"Уведомление отправлено админу {admin_id}")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")


# ─── СТАТИСТИКА ───────────────────────────────────────────
async def weekly_stats(context: ContextTypes.DEFAULT_TYPE):
    stats = load_stats()
    if not stats:
        text = "📊 *Еженедельная статистика*\n\nЗа эту неделю заказов не было."
    else:
        lines = ["📊 *Еженедельная статистика*\n"]
        for worker, records in stats.items():
            lines.append(f"\n👤 {worker}:")
            type_count = defaultdict(int)
            for r in records:
                type_count[r["type"]] += 1
            for t, cnt in type_count.items():
                lines.append(f"  • {t} — {cnt} раз(а)")
        text = "\n".join(lines)

    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(admin_id, text, parse_mode="Markdown")
        except Exception:
            pass
    # Очищаем статистику после отправки
    save_stats({})


# Глобальный объект уведомителя для использования в _notify_admins
notify_bot_app = None

# ─── ЗАПУСК ───────────────────────────────────────────────
import asyncio

async def main():
    global notify_bot_app

    # Основной бот
    app = Application.builder().token(MAIN_TOKEN).build()
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))

    # Еженедельная статистика
    job_queue = app.job_queue
    now_msk = datetime.now(MSK)
    days_until_monday = (7 - now_msk.weekday()) % 7 or 7
    next_monday = now_msk.replace(hour=10, minute=0, second=0, microsecond=0) + timedelta(days=days_until_monday)
    job_queue.run_repeating(
        weekly_stats,
        interval=timedelta(weeks=1),
        first=next_monday,
    )

    # Бот-уведомитель
    notify_app = Application.builder().token(NOTIFY_TOKEN).build()
    notify_app.add_handler(CommandHandler("start", cmd_start_notifier))
    notify_app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.User(ADMIN_IDS),
        notify_code_handler
    ))
    notify_bot_app = notify_app

    logger.info("Оба бота запущены!")

    async with app, notify_app:
        await app.initialize()
        await notify_app.initialize()
        await app.start()
        await notify_app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        await notify_app.updater.start_polling(drop_pending_updates=True)
        await asyncio.Event().wait()
        await app.updater.stop()
        await notify_app.updater.stop()
        await app.stop()
        await notify_app.stop()


async def notify_code_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Админ вводит код UC через бот-уведомитель"""
    if update.message.from_user.id not in ADMIN_IDS:
        return
    code_order = context.user_data.get("awaiting_code_order")
    if not code_order:
        return
    order_id = code_order
    order = orders.get(order_id)
    if order:
        code = update.message.text.strip()
        context.user_data.pop("awaiting_code_order", None)
        try:
            await context.bot.send_message(
                order["user_id"],
                f"✅ *Оплата принята!*\n\n"
                f"🎮 Ваш код UC:\n`{code}`\n\n"
                f"Спасибо за покупку! 🎉",
                parse_mode="Markdown"
            )
            await update.message.reply_text(f"✅ Код отправлен покупателю (заказ #{order_id})")
        except Exception as e:
            await update.message.reply_text(f"❌ Ошибка: {e}")


if __name__ == "__main__":
    asyncio.run(main())
