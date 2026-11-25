from telegram import KeyboardButton, ReplyKeyboardMarkup


MAIN_MENU_LABELS = {
    "📥 Ultimi annunci": "latest",
    "🗂 Storico 3 giorni": "history",
    "📡 Stato": "status",
    "🌐 Fonti": "sources",
    "⚙️ Preferenze": "settings",
    "❔ Aiuto": "help",
}


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("📥 Ultimi annunci"), KeyboardButton("🗂 Storico 3 giorni")],
            [KeyboardButton("📡 Stato"), KeyboardButton("🌐 Fonti")],
            [KeyboardButton("⚙️ Preferenze"), KeyboardButton("❔ Aiuto")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Scegli un comando…",
    )
