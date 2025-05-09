import sys
import configparser
import os

from flask import Flask, request, abort
from linebot.v3 import (
    WebhookHandler
)
from linebot.v3.exceptions import (
    InvalidSignatureError
)
from linebot.v3.webhooks import (
    MessageEvent,
    TextMessageContent,
)
from linebot.v3.messaging import (
    Configuration,
    ApiClient,
    MessagingApi,
    ReplyMessageRequest,
    TextMessage,
    StickerMessage
)

#Config Parser
config = configparser.ConfigParser()
config.read('config.ini')

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold

llm = genai.GenerativeModel(
    "gemini-1.5-flash-latest",
    safety_settings={
        HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_NONE,
        HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_NONE,
    },
    generation_config={
        "temperature": 1,
        "top_p": 0.95,
        "top_k": 64,
        "max_output_tokens": 8192,
    },
)
chat = llm.start_chat(history=[])
# Please replace the content with your own role description
role = """
如果有人下關鍵字"情緒"的話，你就直接判斷後面的語句的情緒分析，回答的格式是"情緒:"後面接這句話的情緒。
除了下關鍵字"情緒"以外，你不要回覆情緒相關的回答。
妳是一個資工電腦專家，別人問妳這個問題妳可以用專業的知識來回答。
但如果有人問妳其他類型的問題，妳也可以回答得很好。
如果別人問你問題，你可以回答
"你好！有什麼我可以幫忙的嗎？  請儘管提出你的問題，無論是關於電腦科學、軟體工程，或是其他任何領域，我都會盡力以專業且清晰的方式回答。"。
除非有人要求你用不同語言回答，不然你都是用繁體中文回答。
"""
genai.configure(api_key=config["Gemini"]["API_KEY"])

chat_history = {}


app = Flask(__name__)

channel_access_token = config['Line']['CHANNEL_ACCESS_TOKEN']
channel_secret = config['Line']['CHANNEL_SECRET']
if channel_secret is None:
    print('Specify LINE_CHANNEL_SECRET as environment variable.')
    sys.exit(1)
if channel_access_token is None:
    print('Specify LINE_CHANNEL_ACCESS_TOKEN as environment variable.')
    sys.exit(1)

handler = WebhookHandler(channel_secret)

configuration = Configuration(
    access_token=channel_access_token
)

city_translation = {
    "台北": "Taipei",
    "新北": "New Taipei",
    "桃園": "Taoyuan",
    "台中": "Taichung",
    "台南": "Tainan",
    "高雄": "Kaohsiung",
    "基隆": "Keelung",
    "新竹": "Hsinchu",
    "嘉義": "Chiayi",
    "南投": "Nantou",
    "宜蘭": "Yilan",
    "花蓮": "Hualien",
    "台東": "Taitung",
    "澎湖": "Penghu",
    "金門": "Kinmen",
    "連江": "Lienchiang"
}
# 建立英文 → 中文對應（自動反轉）
city_translation_reverse = {v: k for k, v in city_translation.items()}

@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']
    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # parse webhook body
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@handler.add(MessageEvent, message=TextMessageContent)
def message_text(event):
    user_message = event.message.text
    user_id = getattr(event.source, "user_id", "anonymous")

    # 初始化使用者歷史
    if user_id not in chat_history:
        chat_history[user_id] = []

    # 查詢 ID
    if user_message.lower() == "id":
        reply_text = f"你的 LINE ID 是：{user_id}"

    elif user_message.endswith("天氣"):
        city = user_message.replace("天氣", "").strip()

        if city == "":
            reply_text = "請輸入城市，例如：台北天氣"
        else:
            city_en = city_translation.get(city, city)  # 找不到就原樣傳入
            reply_text = get_weather(city_en)


    # 發送貼圖
    elif user_message == 'Sticker':
        sticker_msg = StickerMessage(package_id="1", sticker_id="2")
        reply_data = {
            "type": "sticker",
            "package_id": "1",
            "sticker_id": "2"
        }
        chat_history[user_id].append({
            "question": user_message,
            "answer": reply_data
        })
        with ApiClient(configuration) as api_client:
            MessagingApi(api_client).reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[sticker_msg]
                )
            )
        return  # 不處理下面的文字

    # 一般 Gemini 回覆
    else:
        prompt = role + user_message if len(chat.history) == 0 else user_message
        try:
            result = chat.send_message(prompt)
            reply_text = result.text.strip()
        except Exception as e:
            print(e)
            reply_text = "我媽來了，她說不能聊這個(雙手比叉)"

    # 儲存文字回應
    chat_history[user_id].append({
        "question": user_message,
        "answer": reply_text
    })

    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message_with_http_info(
            ReplyMessageRequest(
                reply_token=event.reply_token,
                messages=[TextMessage(text=reply_text)]
            )
        )


import requests

def get_weather(city_name):
    api_key = config["Weather"]["API_KEY"]
    url = f"https://api.openweathermap.org/data/2.5/weather?q={city_name}&appid={api_key}&lang=zh_tw&units=metric"
    try:
        res = requests.get(url, timeout=10)
        data = res.json()

        if data.get("cod") != 200:
            return f"找不到「{city_name}」的天氣資訊。"

        weather = data["weather"][0]["description"]
        temp = data["main"]["temp"]
        feels_like = data["main"]["feels_like"]
        city_zh = city_translation_reverse.get(city_name, city_name)
        return f"{city_zh} 現在天氣「{weather}」，氣溫 {temp:.1f}°C，體感 {feels_like:.1f}°C。"

    except Exception as e:
        print(e)
        return "天氣查詢失敗，請稍後再試。"


# get RESTful API
@app.route("/history/<user_id>", methods=["GET"])
def get_history(user_id):
    history = chat_history.get(user_id, [])
    return {"user_id": user_id, "history": history}, 200

# delete RESTful API
@app.route("/history/<user_id>", methods=["DELETE"])
def delete_history(user_id):
    if user_id in chat_history:
        del chat_history[user_id]
        return {"message": f"Deleted history for user {user_id}"}, 200
    else:
        return {"error": "User not found"}, 404

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))  # Render 預設給你 PORT 變數
    app.run(host="0.0.0.0", port=port)