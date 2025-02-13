import os
import asyncio
from nonebot import get_plugin_config
from nonebot.plugin import PluginMetadata
from nonebot_plugin_waiter import waiter
from nonebot.rule import to_me
from nonebot.plugin import on_command
from nonebot.adapters import Event
from nonebot.adapters.onebot.v11 import MessageSegment, Bot, Message, PrivateMessageEvent
from nonebot.params import CommandArg, ArgPlainText
from .reciever import msg_processer, save_to_temp, download_all_media, json2html, html2pdf, pdf2jpg, submission_msg, cleanup_temp, get_next_folder_name, transform_metadata
from .config import Config, Conf
import os
import json
from nonebot import require
require("Qzone_toolkit")
import mynbwall.plugins.Qzone_toolkit as qzone_toolkit
from nonebot.permission import SUPERUSER



__plugin_meta__ = PluginMetadata(
    name="submissionReciver",
    description="",
    usage="",
    config=Config,
)

config = get_plugin_config(Config)
conf = Conf()


reciever = on_command('投稿', rule=to_me(), priority=5)

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

    async for resp in check(timeout=120): 
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

    # 保存更新后的消息列表到 JSON 文件d
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
deleter = on_command(cmd='del', rule=to_me(), aliases={"删"}, priority=5, permission=SUPERUSER)
@deleter.handle()
async def handle_delete(bot: Bot, event: Event, args: Message = CommandArg()):
    # 提取用户输入的参数（稿件编号）
    param = args.extract_plain_text().strip()

    if param:  # 如果参数存在
        await delete_submission(param)
    else:  # 如果没有参数，要求用户输入
        await deleter.finish("无效，请输入要删除的稿件编号")
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
passer = on_command('pass', aliases={"是"}, rule=to_me(), priority=5, permission=SUPERUSER)
@passer.handle()
async def handle_pass(bot: Bot, event: Event, args: Message = CommandArg()):
    param = args.extract_plain_text().strip()
    if param:
        await send_submission(param, bot)
    else:
        await passer.finish("无效，请输入要通过的稿件编号")
async def send_submission(param: str, bot: Bot):
    folder_path = os.path.join("temp", param)
    submission_file = os.path.join(folder_path, "submission.json")
    await passer.send(submission_file)
    # 验证参数有效性
    if not (param.isdigit() and os.path.exists(folder_path)):
        await passer.finish(f"⚠️ 稿件 {param} 不存在或编号无效")
        return
    await qzone_toolkit.send("#" + str(conf.out_id), folder_path, conf.bot_id)
    await passer.send("已发送")
    if os.path.exists(folder_path) and param.isdigit():
        message_file = os.path.join(folder_path, "messages.json")        

        with open(message_file, 'r', encoding='utf-8') as file:
            message_data = json.load(file)
            
            # 找到sessionID并输出
            session_id = None
            for item in message_data:
                if item.get('type') == 'metadata':
                    session_id = item.get('sessionID')
                    break
            

    await bot.send_private_msg(user_id=session_id, message=f"稿件{param}已通过审核")
    await cleanup_temp(folder_path)







# 创建拒绝命令处理器
refuser = on_command('refuse', rule=to_me(), priority=5,permission=SUPERUSER, aliases={"拒"})
@refuser.handle()
async def handle_refuse(bot: Bot, event: Event, args: Message = CommandArg()):
    # 提取用户输入的参数（稿件编号）
    param = args.extract_plain_text().strip()

    if param:  # 如果参数存在
        await refuse_submission(param, bot)
    else:  # 如果没有参数，要求用户输入
        await refuser.finish("无效，请输入要拒绝的稿件编号")
async def refuse_submission(param: str, bot: Bot):

    folder_path = os.path.join("temp", param)

    # 检查文件夹是否存在且编号是数字
    if os.path.exists(folder_path) and param.isdigit():
        message_file = os.path.join(folder_path, "messages.json")
        
        # 检查message.json文件是否存在
        if os.path.exists(message_file):
            try:
                with open(message_file, 'r', encoding='utf-8') as file:
                    message_data = json.load(file)
                    
                    # 找到sessionID并输出
                    session_id = None
                    for item in message_data:
                        if item.get('type') == 'metadata':
                            session_id = item.get('sessionID')
                            break
                    
                    if session_id:
                        await bot.send_private_msg(user_id=session_id, message="您的稿件已被拒绝，请@交流群管理了解原因或尝试修改后重新投稿")
                    else:
                        await refuser.finish("⚠️ 没有找到有效的 sessionID")
            except json.JSONDecodeError:
                await refuser.finish("🚨 错误：无法解析 messages.json 文件，请检查文件格式")
        else:
            await refuser.finish("⚠️ messages.json 文件不存在")

        # 清理文件夹中的所有文件，但保留文件夹
        await cleanup_temp(folder_path)
        await refuser.finish(f"✅ 已拒绝稿件 {param}")
        
    else:
        await refuser.finish(f"⚠️ 稿件 {param} 不存在或编号无效")



# 创建待处理命令处理器
to_process = on_command('tp', rule=to_me(), priority=5, permission=SUPERUSER, aliases={"待处理"})
@to_process.handle()
async def handle_to_process(bot: Bot, event: Event):
    has_files = get_folders_with_files()
    if has_files:
        await to_process.finish(f"当前有 {len(has_files)} 个待处理稿件：\n{', '.join(has_files)}")
    else:
        await to_process.finish("当前没有待处理稿件")
def get_folders_with_files():
    temp_dir = "temp"
    has_files = []
    # 遍历从1开始递增检查每个数字文件夹
    num = 1
    while True:
        folder_path = os.path.join(temp_dir, str(num))
        if not os.path.isdir(folder_path):
            break  # 当没有该文件夹时停止循环
        # 检查文件夹内是否有文件
        try:
            for item in os.listdir(folder_path):
                item_path = os.path.join(folder_path, item)
                if os.path.isfile(item_path):
                    has_files.append(str(num))
                    break  # 只需检测到至少有一个文件，就记录该num并继续下一个循环
        except Exception as e:
            print(f"Error accessing folder {str(num)}: {e}")
        num += 1
    return has_files



# 创建回复命令处理器
replier = on_command('reply', rule=to_me(), priority=5, permission=SUPERUSER, aliases={"回复"})
@replier.handle()
async def handle_reply(bot: Bot, event: Event, args: Message = CommandArg()):
    # 提取用户输入的参数（稿件编号）
    param = str(args).split(" ")[0]
    reply = str(args).split(" ")[1]
    if param and reply:
        await reply_submission(param, reply, bot)
async def reply_submission(param: str, reply: str, bot: Bot):

    folder_path = os.path.join("temp", param)

    # 检查文件夹是否存在且编号是数字
    if os.path.exists(folder_path) and param.isdigit():
        message_file = os.path.join(folder_path, "messages.json")
        
        # 检查message.json文件是否存在
        if os.path.exists(message_file):
            try:
                with open(message_file, 'r', encoding='utf-8') as file:
                    message_data = json.load(file)
                    
                    # 找到sessionID并输出
                    session_id = None
                    for item in message_data:
                        if item.get('type') == 'metadata':
                            session_id = item.get('sessionID')
                            break
                    
                    if session_id:
                        await bot.send_private_msg(user_id=session_id, message=reply)
                    else:
                        await refuser.finish("⚠️ 没有找到有效的 sessionID")
            except json.JSONDecodeError:
                await refuser.finish("🚨 错误：无法解析 messages.json 文件，请检查文件格式")
        else:
            await refuser.finish("⚠️ messages.json 文件不存在")

        await refuser.finish("回复成功")
        
    else:
        await refuser.finish(f"⚠️ 稿件 {param} 不存在或编号无效")



# 创建展示命令处理器
shower = on_command('show', rule=to_me(), priority=5, permission=SUPERUSER, aliases={"展示"})
@shower.handle()
async def handle_show(bot: Bot, event: Event, args: Message = CommandArg()):

    param = str(args).strip()
    if param:
        path = os.path.join('temp', param)
        await shower.finish(await submission_msg(path))
    else:
        await shower.finish("无效，请输入要展示的稿件编号")



# 创建帮助命令处理器
admin_helper = on_command('help', rule=to_me(), priority=5, permission=SUPERUSER, aliases={"帮助"}, block=True)
@admin_helper.handle()
async def handle_help(bot: Bot, event: Event):
    await admin_helper.finish(conf.help_msg_admin)



# 创建帮助命令处理器
helper = on_command('help', rule=to_me(), priority=5, permission=SUPERUSER, aliases={"帮助"})
@helper.handle()
async def handle_help(bot: Bot, event: Event):
    await helper.finish(conf.help_msg)



# 创建设定编号命令处理器
set_id = on_command('setid', rule=to_me(), priority=5, aliases={"设定编号"}, permission=SUPERUSER)
@set_id.handle()
async def handle_set_id(bot: Bot, event: Event, args: Message = CommandArg()):
    param = args.extract_plain_text().strip()
    if param:
        await set_out_id(param)
    else:
        await set_id.finish("无效，请输入要设定的编号")

async def set_out_id(param: str):
    if param.isdigit():
        conf.out_id = int(param)
        await set_id.finish(f"✅ 已设定下一个稿件编号为 {param}")