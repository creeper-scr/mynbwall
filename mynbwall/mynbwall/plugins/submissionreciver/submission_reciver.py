import os
import json
import re
import aiofiles
import httpx
import ssl
import traceback

from typing import List
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot_plugin_waiter import waiter
from nonebot.rule import to_me
from nonebot.plugin import on_command
from nonebot.adapters import Event, Message
from nonebot.adapters.onebot.v11 import MessageSegment, Bot


from .config import Config

__plugin_meta__ = PluginMetadata(
    name="submissionReciver",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

reciever = on_command('test', rule=to_me(), priority=5)

# 定义一个插件类
class SubmissionReceiver:
    def __init__(self):
        self.received_messages = []  # 用于存储收到的所有消息
        self.folder_name = None  # 用于存储文件夹名称

    def get_next_folder_name(self):
        """
        获取 temp 文件夹中下一个可用的编号文件夹名称（纯数字递增）
        """
        base_folder = "temp"
        folder_index = 1  # 从1开始

        # 查找temp文件夹下的所有子文件夹
        existing_folders = [f for f in os.listdir(base_folder) if os.path.isdir(os.path.join(base_folder, f))]
        
        # 遍历现有文件夹并找到最后的编号
        if existing_folders:
            # 获取文件夹名称中的数字并找到最大值
            folder_index = max([int(f) for f in existing_folders if f.isdigit()]) + 1

        return os.path.join(base_folder, str(folder_index))

    async def msg_processer(self, msg: Message, sessionID: str):
        """
        处理接收到的消息并将其分为文本、图片等类型
        """
        processed_messages = []
        
        # 用于确保只在第一次添加 metadata
        if not processed_messages:  # 只在第一次添加 metadata
            processed_messages.append({
                'type': 'metadata',
                'sessionID': sessionID  # 将 sessionID 写入元数据
            })

        # 遍历消息序列中的每个消息段
        for segment in msg:
            if segment.type == 'text':
                # 处理文本消息
                processed_messages.append({
                    'type': 'text',
                    'content': segment.data['text']
                })
            elif segment.type == 'face':
                await reciever.send("暂不支持qq表情，投稿流程已终止。请删去表情后重新投稿")
                return []  # 返回空列表终止处理
            elif segment.type == 'image':
                # 处理图片和表情包
                if segment.data['subType'] == 0:
                    processed_messages.append({
                        'type': 'image',
                        'content': segment.data['url'],
                        'file': segment.data['file']
                    })
                else:
                    processed_messages.append({
                        'type': 'meme',
                        'content': segment.data['url'],
                        'file': segment.data['file']
                    })
            else:
                await reciever.send("暂不支持此类型消息，投稿流程已终止。请重新投稿")
                return []  # 返回空列表终止处理

        return processed_messages

    async def save_to_temp(self, data, folder_name):
        """
        将处理后的消息数据保存到 JSON 文件
        """
        try:
            # 确保只插入一次 metadata
            all_messages = []
            metadata_added = False  # 用于检查是否已经插入过 metadata
            
            for message_group in data:
                for msg in message_group:
                    # 只插入一次 metadata
                    if msg['type'] == 'metadata' and not metadata_added:
                        all_messages.append(msg)
                        metadata_added = True
                    elif msg['type'] != 'metadata':
                        all_messages.append(msg)

            # 保存到 JSON 文件
            file_path = os.path.join(folder_name, "messages.json")
            async with aiofiles.open(file_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(all_messages, ensure_ascii=False, indent=4))
            
            print(f"所有消息已保存到 {file_path}")
            return f"JSON 文件已保存：{file_path}"
        
        except Exception as e:
            print(f"保存文件时出错: {e}")
            return f"保存文件时出错: {e}"

    async def download_all_media(self, messages, folder_name):
        """
        下载所有的媒体文件（图片、表情包等）并更新消息中的内容为本地文件名
        """
        for message_group in messages:
            for msg in message_group:
                # 确保 msg 是一个包含 'content' 键的字典
                if 'content' in msg:
                    if msg['type'] in ['image', 'meme']:
                        url = msg['content']
                        file_name = re.sub(r'[\\/:*?"<>|]', '_', msg['file'])  # 清理非法字符
                        file_path = await self.download_image(url, file_name, folder_name)

                        if file_path:
                            # 更新消息中的图片 URL 为本地路径的文件名
                            msg['content'] = os.path.basename(file_path)  # 只保留文件名（包括扩展名）

    async def download_image(self, url, file_name, folder_name):
        """
        下载图片并保存到指定路径
        """
        try:
            file_extension = self.get_file_extension(file_name)

            # 创建 SSL 上下文
            ssl_context = ssl.create_default_context()
            ssl_context.options |= ssl.OP_NO_TLSv1 | ssl.OP_NO_TLSv1_1 | ssl.OP_NO_TLSv1_3
            ssl_context.set_ciphers("HIGH:!aNULL:!MD5")

            # 使用 httpx 异步客户端发送 GET 请求，并传递自定义的 SSL 上下文
            async with httpx.AsyncClient(verify=ssl_context) as client:
                response = await client.get(url)

                if response.status_code == 200:
                    # 如果没有扩展名，添加扩展名
                    file_path_with_extension = os.path.join(folder_name, file_name)
                    if not file_name.lower().endswith(file_extension):
                        file_path_with_extension += file_extension

                    with open(file_path_with_extension, 'wb') as f:
                        f.write(response.content)
                    print(f"图片已成功下载并保存在 {file_path_with_extension}")
                    return file_path_with_extension
                else:
                    print(f"下载失败，状态码: {response.status_code}")
                    return None
        except Exception as e:
            print(f"下载图片时出错: {e}")
            traceback.print_exc()
            return None

    def get_file_extension(self, file_name):
        """
        根据文件名返回文件扩展名，若无扩展名则默认返回 .jpg
        """
        _, file_extension = os.path.splitext(file_name)
        return file_extension.lower() if file_extension else '.jpg'

    async def json2html(self, json_path):
        html_path = f"{json_path.replace('.json', '.html')}"
        if not os.path.exists(json_path):
            return "生成 HTML 失败：文件不存在。"

        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as e:
            return f"生成 HTML 失败：JSON 解析错误 - {str(e)}"

        processed_messages = []
        sessionID = None

        # 解析消息内容
        for item in data:
            if item.get("type") == "metadata":
                sessionID = item.get("sessionID", "")
                continue

            if item.get("type") == "text":
                content = item.get("content", "")
                escaped_msg = (
                    content.replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                    .replace('"', "&quot;")
                    .replace("'", "&#039;")
                )
                escaped_msg = escaped_msg.replace("\n", "<br/>")
                processed_messages.append(f'<div>{escaped_msg}</div>')

            elif item.get("type") in ["meme", "image"]:
                img_path = item.get("content", "").replace("\\", "/")
                # 生成绝对路径
                img_abs_path = os.path.abspath(
                    os.path.join(os.path.dirname(json_path), img_path)
                )
                # 使用 file:// 协议
                processed_messages.append(
                    f'<img src="file://{img_abs_path}" alt="{item["type"]}">'
                )

        # 验证 sessionID
        if not sessionID:
            return "生成 HTML 失败：未找到 sessionID"
        # 生成 HTML 内容（保持原模板不变）
        html_content = f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Session {sessionID}</title>
<style>
        @page {{
          margin: 0 !important;
          size:4in 8in;
        }}
        body {{
            font-family: Arial, sans-serif;
            background-color: #f2f2f2;
            margin: 0;
            padding: 5px;
        }}
        .container {{
            width: 4in;
            margin: 0 auto;
            padding: 20px;
            border-radius: 10px;
            background-color: #f2f2f2;
            box-sizing: border-box;
        }}
        .header {{
            display: flex;
            align-items: center;
        }}
        .header img {{
            border-radius: 50%;
            width: 50px;
            height: 50px;
            margin-right: 10px;
            box-shadow: 0 0 10px rgba(0, 0, 0, 0.3);
        }}
        .header-text {{
            display: block;
        }}
        .header h1 {{
            font-size: 24px;
            margin: 0;
        }}
        .header h2 {{
            font-size: 12px;
            margin: 0;
        }}
        .content {{
            margin-top: 20px;
        }}
        .content div{{
            display: block;
            background-color: #ffffff;
            border-radius: 10px;
            padding: 7px;
            margin-bottom: 10px;
            word-break: break-word;
            max-width: fit-content;
            line-height: 1.5;
        }}
        .content img, .content video {{
            display: block;
            border-radius: 10px;
            padding: 0px;
            margin-top: 10px;
            margin-bottom: 10px;
            max-width: 50%;
            max-height: 300px; 
        }}
        .content video {{
            background-color: transparent;
        }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="header-text">
                <h1>{sessionID}</h1>
                <h2></h2>
            </div>
        </div>
        <div class="content">
            {''.join(processed_messages)}
        </div>
    </div>
</body>
</html>
"""

        # 写入文件
        os.makedirs(os.path.dirname(html_path), exist_ok=True)
        try:
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html_content)
            return html_path
        except Exception as e:
            return str(e)