from fastapi import Request
from fastapi.responses import PlainTextResponse
import hashlib
from adapters.wechat import WeChatAdapter

# 微信公众号配置（从环境变量读取）
import os

WX_TOKEN = os.getenv("WX_TOKEN", "")
WX_APP_ID = os.getenv("WX_APP_ID", "")
WX_APP_SECRET = os.getenv("WX_APP_SECRET", "")

wx_adapter = WeChatAdapter(token=WX_TOKEN, app_id=WX_APP_ID, app_secret=WX_APP_SECRET)


async def wechat_verify(request: Request):
    """微信服务器 Token 验证（GET）"""
    params = request.query_params
    signature = params.get("signature", "")
    timestamp = params.get("timestamp", "")
    nonce = params.get("nonce", "")
    echostr = params.get("echostr", "")

    if wx_adapter.verify_signature(signature, timestamp, nonce):
        return PlainTextResponse(echostr)
    return PlainTextResponse("verification failed", status_code=403)


async def wechat_callback(request: Request, llm, db):
    """接收微信消息并回复（POST）— v2 兼容 Database 接口"""
    xml_data = await request.body()
    msg = wx_adapter.parse_message(xml_data.decode("utf-8"))

    if not msg or msg["type"] != "text":
        return PlainTextResponse("success")

    user_content = msg["content"]
    from_user = msg["from_user"]
    to_user = msg["to_user"]

    messages = [
        {"role": "system", "content": "你是微信上的 AI 助手，回复简洁友好。"},
        {"role": "user", "content": user_content},
    ]

    try:
        reply = llm.chat(messages, stream=False)
        parts = wx_adapter.split_long_reply(reply, max_len=600)
        first = parts[0]
    except Exception:
        first = "抱歉，我暂时无法回答，请稍后再试。"

    return PlainTextResponse(
        wx_adapter.build_reply(to_user, from_user, first),
        media_type="application/xml",
    )
