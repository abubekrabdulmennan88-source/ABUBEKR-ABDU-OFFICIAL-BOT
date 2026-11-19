import os
import httpx
from telegram.ext import (ApplicationBuilder, CommandHandler,
                          MessageHandler, filters)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "የቦት_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_KEY", "የGemini_KEY")
# ሞዴሉ ከተቀየረ በ Google AI Studio የአሁኑን ስም ይመልከቱ
GEMINI_MODEL = "gemini-2.0-flash"

SYSTEM_PROMPT = (
    "አንተ ስለ እስልምና ጥያቄዎችን የምትመልስ ረዳት ነህ። "
    "መልስ ከመስጠትህ በፊት ሁልጊዜ በድር ላይ ፈልግ። "
    "በተለይ ከታማኝ የዓሊሞች ምንጮች ፈልግ፦ ኢብን ባዝ (binbaz.org.sa)፣ "
    "ኢብን ዑሰይሚን (ibnothaimeen.com)፣ ኢብን ተይሚያ (መጅሙዑል ፈታዋ)፣ "
    "እና islamqa.info። "
    "በአማርኛ መልስ፤ መልስህ አጭር እና ግልጽ ይሁን። "
    "የተጠቀምክበትን ዓሊም ስም ጥቀስ፤ አስፈላጊ ከሆነ ዋናውን የዐረብኛ ጽሑፍ አሳይ። "
    "ዓሊሞች የተለያየ አስተያየት ካላቸው ሁሉንም ጥቀስ። "
    "ምንጭ ካላገኘህ ወይም እርግጠኛ ካልሆንክ 'አላገኘሁም' በል፤ ከራስህ አትፍጠር።"
)

DISCLAIMER = "\n\n⚠️ ይህ በ AI የተሰጠ መልስ ነው። ለዝርዝር ጉዳይ ዓሊም ያማክሩ።"


async def ask_gemini(question: str) -> str:
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{GEMINI_MODEL}:generateContent"
    )
    body = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        # Gemini ራሱ በ Google ላይ እንዲፈልግ
        "tools": [{"google_search": {}}],
    }
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(url, params={"key": GEMINI_KEY}, json=body)
        r.raise_for_status()
        data = r.json()

    cand = data["candidates"][0]
    text = "".join(p.get("text", "") for p in cand["content"]["parts"])

    # የተጠቀመባቸውን ድረ-ገጾች ማሳየት
    chunks = cand.get("groundingMetadata", {}).get("groundingChunks", [])
    links = []
    for c in chunks[:4]:
        web = c.get("web", {})
        if web.get("title"):
            links.append(f"• {web['title']}")
    if links:
        text += "\n\nምንጮች፦\n" + "\n".join(links)
    return text


async def start(update, context):
    await update.message.reply_text(
        "ሰላም! ስለ እስልምና ጥያቄዎን ይጠይቁ፤ በድር ላይ ፈልጌ በአማርኛ እመልሳለሁ።"
    )


async def reply(update, context):
    await update.message.chat.send_action("typing")
    try:
        answer = await ask_gemini(update.message.text)
        # ቴሌግራም ከ4096 ፊደል በላይ አይቀበልም
        await update.message.reply_text(answer[:3800] + DISCLAIMER)
    except Exception:
        await update.message.reply_text(
            "ይቅርታ፣ አሁን መልስ መስጠት አልቻልኩም። ቆይተው ይሞክሩ።"
        )


app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, reply))
app.run_polling()
