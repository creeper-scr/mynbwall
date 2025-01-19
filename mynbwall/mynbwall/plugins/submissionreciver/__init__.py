import os
import json
import time
import re
import httpx
import ssl
import traceback
import aiofiles
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot_plugin_waiter import waiter
from nonebot.rule import to_me
from nonebot.plugin import on_command
from nonebot.adapters import Event, Message
from jinja2 import Template
from PIL import Image
import weasyprint
import fitz  # PyMuPDF

from .config import Config

__plugin_meta__ = PluginMetadata(
    name="submissionReciver",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)

reciever = on_command('test', rule=to_me(), priority=5)

# 用于存储收到的所有消息
received_messages = []


@reciever.handle()
async def recieve(bot, event):
    # 创建一个唯一的文件夹名称，使用时间戳作为标识符
    timestamp = int(time.time())
    folder_name = os.path.join("temp", str(timestamp))

    # 创建该文件夹（如果不存在）
    os.makedirs(folder_name, exist_ok=True)

    await reciever.send("请在接下来的 2 分钟内发送消息")

    @waiter(waits=["message"], keep_session=True)
    async def check(event: Event):
        return event.get_message()

    async for resp in check(timeout=10, default=''):
        if not resp:
            await reciever.send("接收超时")
            break

        # 处理消息并保存到列表
        result = await msg_processer(resp)
        received_messages.append(result)
        await reciever.send(f"收到消息: {repr(resp)}")

    # 超过时间后保存所有消息到 JSON 文件
    await save_to_temp(received_messages, folder_name)

    # 下载所有媒体文件到该文件夹
    await download_all_media(received_messages, folder_name)

    # 保存更新后的消息列表到 JSON 文件
    await save_to_temp(received_messages, folder_name)
    await turn2img(os.path.join(folder_name, "messages.json"), folder_name)


async def msg_processer(msg: Message):
    """
    处理接收到的消息并将其分为文本、图片等类型
    """
    processed_messages = []

    # 遍历消息序列中的每个消息段
    for segment in msg:
        if segment.type == 'text':
            # 处理文本消息
            processed_messages.append({
                'type': 'text',
                'content': segment.data['text']
            })
        elif segment.type == 'face':
            reciever.finish("暂不支持qq表情，投稿流程已终止。请删去表情后重新投稿")
        elif segment.type in ['image', 'meme']:
            # 处理图片和表情包
            processed_messages.append({
                'type': segment.type,
                'content': segment.data['url'],
                'file': segment.data['file']
            })
        else:
            reciever.finish("暂不支持此类型消息，投稿流程已终止。请重新投稿")

    return processed_messages


async def save_to_temp(data, folder_name):
    """
    将处理后的消息数据保存到 JSON 文件
    """
    file_path = os.path.join(folder_name, "messages.json")
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
        
    print(f"所有消息已保存到 {file_path}")


async def download_image(url, file_name, folder_name):
    """
    下载图片并保存到指定路径
    """
    try:
        file_extension = get_file_extension(file_name)

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


def get_file_extension(file_name):
    """
    根据文件名返回文件扩展名，若无扩展名则默认返回 .jpg
    """
    _, file_extension = os.path.splitext(file_name)
    return file_extension.lower() if file_extension else '.jpg'


async def download_all_media(messages, folder_name):
    """
    下载所有的媒体文件（图片、表情包等）并更新消息中的内容为本地路径
    """
    for message_group in messages:
        for msg in message_group:
            if msg['type'] in ['image', 'meme']:
                url = msg['content']
                file_name = re.sub(r'[\\/:*?"<>|]', '_', msg['file'])  # 清理非法字符
                file_path = await download_image(url, file_name, folder_name)

                if file_path:
                    for message_group in messages:
                        for m in message_group:
                            if m['content'] == url:
                                m['content'] = file_path


async def read_json_file(json_file):
    """
    异步读取 JSON 文件并返回内容
    """
    async with aiofiles.open(json_file, 'r', encoding='utf-8') as file:
        return json.loads(await file.read())


async def generate_html_file(chat_data, filename):
    """
    使用 Jinja2 模板将聊天数据生成 HTML 文件
    """
    # 扁平化数据，处理消息中的内容
    flat_chat_data = []
    for message_group in chat_data:
        for message in message_group:
            flat_chat_data.append({
                'type': message['type'],
                'content': message['content'],
                'file': message.get('file', ''),
                'sender': "User",  # 假设发送者是 "User"，你可以根据需要修改
                'sender_avatar': "",  # 如果没有头像，设置为空
            })

    # 使用 Jinja2 渲染模板
    template = Template(html_template)
    rendered_html = template.render(chat_data=flat_chat_data)

    async with aiofiles.open(filename, 'w', encoding='utf-8') as file:
        await file.write(rendered_html)


async def convert_html_to_image(html_file, image_file):
    """
    将 HTML 文件转换为图片
    """
    try:
        # 使用 weasyprint 生成 PDF
        pdf_file = image_file.replace(".png", ".pdf")
        weasyprint.HTML(html_file).write_pdf(pdf_file)

        # 使用 PyMuPDF (fitz) 将 PDF 转换为图片
        doc = fitz.open(pdf_file)
        page = doc.load_page(0)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))  # 更高的 DPI
        pix.save(image_file)
        print(f"生成图片: {image_file}")
    except Exception as e:
        print(f"转换失败: {e}")


async def turn2img(json_file, output_dir):
    """
    生成 HTML 文件并转换为图片
    """
    # 这里的 `json_file` 是文件路径
    chat_data = await read_json_file(json_file)  # 读取 JSON 文件

    # 转换路径中的反斜杠为斜杠
    for message_group in chat_data:
        for message in message_group:
            if 'content' in message:
                message['content'] = message['content'].replace("\\", "/")  # 替换反斜杠为斜杠

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    html_filename = os.path.join(output_dir, "chat.html")
    await generate_html_file(chat_data, html_filename)

    image_filename = os.path.join(output_dir, "chat_image.png")
    await convert_html_to_image(html_filename, image_filename)

html_template = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat Record</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            background-color: #f4f4f4;
            margin: 0;
            padding: 0;
            display: flex;
            justify-content: center;
            align-items: flex-start;
            height: 100vh;
            padding-top: 20px;
        }

        .chat-container {
            background-color: white;
            width: 450px;
            max-width: 100%;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.1);
            overflow-y: auto;
            max-height: 80vh;
        }

        .message {
            margin-bottom: 15px;
            display: flex;
            flex-direction: column;
            max-width: 100%;
        }

        .message-content {
            margin-top: 5px;
            padding: 10px;
            border-radius: 8px;
            background-color: white; /* 白色气泡背景 */
            max-width: 75%;
            word-wrap: break-word;
            box-shadow: 0px 0px 10px rgba(0, 0, 0, 0.1); /* 气泡的阴影 */
        }

        img {
            max-width: 150px;
            max-height: 150px;
            border-radius: 5px;
            cursor: pointer;
            display: block;
        }

        .image-container {
            display: inline-block;
            text-align: center;
        }

        .sender-avatar {
            width: 35px;
            height: 35px;
            border-radius: 50%;
            margin-right: 10px;
            background-color: white; /* 白色背景 */
            display: flex;
            justify-content: center;
            align-items: center;
            font-size: 1.2em;
            color: #4A90E2; /* 文字颜色 */
            border: 2px solid #ddd; /* 边框 */
        }

        .message-container {
            display: flex;
            flex-direction: row;
        }

        .message .sender-avatar {
            margin-left: 10px;
        }
    </style>
</head>
<body>

<div class="chat-container">
    {% for message in chat_data %}
        <div class="message">
            <div class="message-container">
                <!-- 如果没有头像，使用默认的白色背景 -->
                <div class="sender-avatar">
                    {% if message.sender_avatar %}
                        <img src="{{ message.sender_avatar }}" alt="avatar" />
                    {% else %}
                        {{ message.sender[0] }} <!-- 默认显示发送者名字首字母 -->
                    {% endif %}
                </div>
                <div>
                    <div class="message-content">
                        {% if message.type == 'text' %}
                            {{ message.content }}
                        {% elif message.type == 'image' %}
                            <div class="image-container">
                                <img src="{{ message.content }}" alt="image"/>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
    {% endfor %}
</div>

</body>
</html>

"""

