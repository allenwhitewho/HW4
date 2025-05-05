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
妳是一個資工電腦專家，別人問妳這個問題妳可以用專業的知識來回答。
但如果有人問妳其他類型的問題，妳也可以回答得很好。
以下是對方問的問題，你直接用這個角色回答就好，不用再舉例。
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
    if user_message == 'Sticker':
        reply_text = StickerMessage(
            package_id="1",
            sticker_id="2"
        )
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[reply_text]
                )
            )
    else:
        prompt = role + user_message if len(chat.history) == 0 else user_message
        try:
            result = chat.send_message(prompt)
            reply_text = result.text.strip()
        except Exception as e:
            print(e)
            reply_text = "我媽來了，她說不能聊這個(雙手比叉)"
        
        with ApiClient(configuration) as api_client:
            line_bot_api = MessagingApi(api_client)
            line_bot_api.reply_message_with_http_info(
                ReplyMessageRequest(
                    reply_token=event.reply_token,
                    messages=[TextMessage(text=reply_text)]
                )
            )
    # 組合角色與對話
    user_id = getattr(event.source, "user_id", "anonymous")
    print("使用者 ID：", user_id)

    # 初始化該使用者的歷史對話
    if user_id not in chat_history:
        chat_history[user_id] = []

    chat_history[user_id].append({
        "question": user_message,
        "answer": reply_text
    })

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