import os
import asyncio
import shutil
from typing import List
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot_plugin_waiter import waiter
from nonebot.rule import to_me
from nonebot.plugin import on_command
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageSegment, Bot, Message
from nonebot.params import CommandArg, ArgPlainText
from .reciever import msg_processer, save_to_temp, download_all_media, json2html, html2pdf, pdf2jpg, submission_msg, cleanup_temp, get_next_folder_name
from .config import Config, Conf
import importlib.util
import sys
import os
import subprocess
import json
from .qzone_tools import renewcookies, send_qzone




__plugin_meta__ = PluginMetadata(
    name="submissionReciver",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)
conf = Conf()


reciever = on_command('test', rule=to_me(), priority=5)

# 用于存储收到的所有消息
received_messages = []

@reciever.handle()
async def recieve(bot: Bot, event: Event):
    # 创建唯一数字序号文件夹
    folder_name = get_next_folder_name()
    os.makedirs(folder_name, exist_ok=True)

    # 接收消息阶段
    await reciever.send("请在接下来的 2 分钟内发送消息")

    @waiter(waits=["message"], keep_session=True)
    async def check(event: Event):
        sessionID = event.get_session_id()
        return [event.get_message(), sessionID]

    async for resp in check(timeout=5): 
        if not resp:
            await reciever.send("投稿时间结束，正在渲染稿件")
            break

        # 处理消息并保存到列表
        result = await msg_processer(resp[0], resp[1])
        received_messages.append(result)
    
    if not received_messages:
        await reciever.finish("⚠️ 未收到任何消息，投稿流程已终止")
    # 超过时间后保存所有消息到 JSON 文件
    await save_to_temp(received_messages, folder_name)
    # 下载所有媒体文件到该文件夹
    await download_all_media(received_messages, folder_name)

    # 保存更新后的消息列表到 JSON 文件
    await save_to_temp(received_messages, folder_name)
    # 生成 HTML 文件
    await json2html(os.path.join(folder_name, "messages.json"))
    # 生成 PDF 文件
    await html2pdf(os.path.join(folder_name, "messages.html"))
    await pdf2jpg(os.path.join(folder_name, 'messages.pdf'))
    await reciever.send(await submission_msg(folder_name))
    await reciever.send("请在一分钟内确认投稿，输入 y 确认或 n 取消")

    # 确认阶段
    @waiter(waits=["message"], keep_session=True)
    async def confirm_check(event: Event):
        # 仅返回用户输入，标准化处理
        return str(event.get_message()).strip().lower()

    try:
        # 使用 async for 获取用户输入
        async for confirm in confirm_check(timeout=60):
            # 获取文件夹编号
            folder_id = os.path.basename(folder_name)
            
            if confirm == "y":
                # 推送审核
                await bot.send_group_msg(
                    group_id=conf.checkgroup,
                    message=MessageSegment.text(f"新稿件（ID: {folder_id}）待审核：\n") 
                    + await submission_msg(folder_name)
                )
                await reciever.finish(f"✅ 稿件 {folder_id} 已提交审核")
            elif confirm == "n":
                await cleanup_temp(folder_name)
                await reciever.finish("❌ 投稿已取消")
            else:
                await cleanup_temp(folder_name)
                await reciever.finish("⚠️ 输入无效，操作已终止")
            
    except asyncio.TimeoutError:
        await cleanup_temp(folder_name)
        await reciever.finish("⏰ 确认超时，投稿流程已终止")



# 创建删除命令处理器
deleter = on_command('del', rule=to_me(), priority=5)
@deleter.handle()
async def handle_delete(bot: Bot, event: Event, args: Message = CommandArg()):
    # 提取用户输入的参数（稿件编号）
    param = args.extract_plain_text().strip()

    if param:  # 如果参数存在
        await delete_submission(param)
    else:  # 如果没有参数，要求用户输入
        await deleter.send("请输入要删除的稿件编号")
        await deleter.got("param", prompt="请输入稿件编号以进行删除：")
@deleter.got("param")
async def got_delete_param(param: str = ArgPlainText()):
    # 用户输入了参数后执行删除操作
    await delete_submission(param)
async def delete_submission(param: str):
    folder_path = os.path.join("temp", param)

    # 检查文件夹是否存在且编号是数字
    if os.path.exists(folder_path) and param.isdigit():
        # 清理文件夹中的所有文件，但保留文件夹
        await cleanup_temp(folder_path)
        await deleter.finish(f"✅ 已删除稿件 {param}")
    else:
        await deleter.finish(f"⚠️ 稿件 {param} 不存在或编号无效")



# 创建通过命令处理器
passer = on_command('pass', rule=to_me(), priority=5)
# 通过命令
@passer.handle()
async def handle_pass(bot: Bot, event: Event, args: Message = CommandArg()):
    param = args.extract_plain_text().strip()
    
    if not param:
        await passer.send("⚠️ 请提供稿件编号")
        return  # 防止后续代码继续执行

    if not param.isdigit():
        await passer.send("⚠️ 稿件编号必须是数字")
        return  # 防止继续执行无效操作

    await send_submission(param)
@passer.got("param")
async def got_pass_param(param: str = ArgPlainText()):
    await send_submission(param)
async def send_submission(param: str):
    folder_path = os.path.join("temp", param)
    submission_file = os.path.join(folder_path, "submission.json")
    await passer.send(submission_file)
    # 验证参数有效性
    if not (param.isdigit() and os.path.exists(folder_path)):
        await passer.finish(f"⚠️ 稿件 {param} 不存在或编号无效")
        return

    try:
        result = await send_qzone(conf.bot_id, conf.send_text, param)
        await passer.finish(result)
            
    except Exception as e:
        await passer.finish(f"🚨 发生错误：{str(e)}，请截图并联系管理员")