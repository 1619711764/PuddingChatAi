# WeChat 消息适配器
# 对接微信公众号 / 企业微信的消息收发

import hashlib
import xml.etree.ElementTree as ET
import time
from typing import Optional


class WeChatAdapter:
    """微信公众号消息处理"""

    def __init__(self, token: str, app_id: str = "", app_secret: str = ""):
        self.token = token
        self.app_id = app_id
        self.app_secret = app_secret

    def verify_signature(self, signature: str, timestamp: str, nonce: str) -> bool:
        """验证微信服务器签名"""
        tmp = sorted([self.token, timestamp, nonce])
        tmp_str = "".join(tmp)
        return hashlib.sha1(tmp_str.encode()).hexdigest() == signature

    def parse_message(self, xml_data: str) -> Optional[dict]:
        """解析微信发来的 XML 消息"""
        try:
            root = ET.fromstring(xml_data)
            msg = {child.tag: child.text for child in root}
            return {
                "from_user": msg.get("FromUserName", ""),
                "to_user": msg.get("ToUserName", ""),
                "type": msg.get("MsgType", "text"),
                "content": msg.get("Content", ""),
                "msg_id": msg.get("MsgId", ""),
                "create_time": msg.get("CreateTime", ""),
            }
        except ET.ParseError:
            return None

    def build_reply(self, to_user: str, from_user: str, content: str) -> str:
        """构造微信 XML 回复"""
        return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[text]]></MsgType>
<Content><![CDATA[{content}]]></Content>
</xml>"""

    def build_news_reply(self, to_user: str, from_user: str, articles: list[dict]) -> str:
        """构造图文消息回复"""
        items = ""
        for a in articles[:8]:
            items += f"""<item>
<Title><![CDATA[{a.get('title', '')}]]></Title>
<Description><![CDATA[{a.get('desc', '')}]]></Description>
<PicUrl><![CDATA[{a.get('pic_url', '')}]]></PicUrl>
<Url><![CDATA[{a.get('url', '')}]]></Url>
</item>"""
        return f"""<xml>
<ToUserName><![CDATA[{to_user}]]></ToUserName>
<FromUserName><![CDATA[{from_user}]]></FromUserName>
<CreateTime>{int(time.time())}</CreateTime>
<MsgType><![CDATA[news]]></MsgType>
<ArticleCount>{len(articles)}</ArticleCount>
<Articles>{items}</Articles>
</xml>"""

    def split_long_reply(self, content: str, max_len: int = 600) -> list[str]:
        """长文本拆分（微信单条回复限制 2048 字符）"""
        if len(content) <= max_len:
            return [content]
        parts = []
        start = 0
        while start < len(content):
            end = min(start + max_len, len(content))
            if end < len(content):
                # 尽量在句号或换行处断开
                for sep in ["\n\n", "\n", "。", ".", "；", ";"]:
                    pos = content.rfind(sep, start, end)
                    if pos > start + max_len // 2:
                        end = pos + 1
                        break
            parts.append(content[start:end])
            start = end
        return parts
