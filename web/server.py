# -*- coding: utf-8 -*-
import asyncio
from datetime import datetime
import functools
import importlib
import json
import logging
import shutil
import sys
import threading
from io import StringIO

import websockets
from flask import Flask, request, jsonify, render_template, make_response, redirect, url_for, send_from_directory
from flask_cors import CORS
from cryptography.fernet import Fernet
from ruamel.yaml import YAML, comments
from threading import Thread
import subprocess
import os
import time
from ruamel.yaml.scalarint import ScalarInt
from ruamel.yaml.scalarstring import DoubleQuotedScalarString, SingleQuotedScalarString, ScalarString

import colorlog

# 全局变量，用于存储 logger 实例和屏蔽的日志类别
_logger = None
_blocked_loggers = []


def createLogger(blocked_loggers=None):
    global _logger, _blocked_loggers
    if blocked_loggers is not None:
        _blocked_loggers = blocked_loggers

    # 确保日志文件夹存在
    log_folder = "log"
    if not os.path.exists(log_folder):
        os.makedirs(log_folder)

    # 创建一个 logger 对象
    logger = logging.getLogger("Eridanus")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # 防止重复日志

    # 自定义过滤器，用于屏蔽指定的日志类别
    class BlockLoggerFilter(logging.Filter):
        def filter(self, record):
            # 过滤器增强：按记录来源和日志类别精确屏蔽
            if record.levelname in _blocked_loggers:
                return False
            return True

    # 设置控制台日志格式和颜色
    console_handler = logging.StreamHandler()
    console_format = '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - [bot] %(message)s'
    console_colors = {
        'DEBUG': 'white',
        'INFO': 'cyan',
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
    console_formatter = colorlog.ColoredFormatter(console_format, log_colors=console_colors)
    console_handler.setFormatter(console_formatter)
    console_handler.addFilter(BlockLoggerFilter())  # 添加过滤器
    logger.addHandler(console_handler)

    # --- 增加颜色区分消息和功能 ---
    console_format_msg = '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - [MSG] %(message)s'
    console_format_func = '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - [FUNC] %(message)s'
    console_colors_msg = {
        'DEBUG': 'white',
        'INFO': 'green',  # 服务器接收的消息用绿色
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
    console_colors_func = {
        'DEBUG': 'white',
        'INFO': 'blue',  # 功能信息用蓝色
        'WARNING': 'yellow',
        'ERROR': 'red',
        'CRITICAL': 'bold_red',
    }
    console_formatter_msg = colorlog.ColoredFormatter(console_format_msg, log_colors=console_colors_msg)
    console_formatter_func = colorlog.ColoredFormatter(console_format_func, log_colors=console_colors_func)

    # 设置文件日志格式
    file_format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    file_formatter = logging.Formatter(file_format)

    # 获取当前日期
    current_date = datetime.now().strftime("%Y-%m-%d")
    log_file_path = os.path.join(log_folder, f"{current_date}.log")

    # 创建文件处理器
    file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
    file_handler.setFormatter(file_formatter)
    file_handler.addFilter(BlockLoggerFilter())  # 添加过滤器
    logger.addHandler(file_handler)

    # 定义一个函数来更新日志文件（按日期切换）
    def update_log_file():
        nonlocal log_file_path, file_handler
        new_date = datetime.now().strftime("%Y-%m-%d")
        new_log_file_path = os.path.join(log_folder, f"{new_date}.log")
        if new_log_file_path != log_file_path:
            logger.removeHandler(file_handler)
            file_handler.close()
            log_file_path = new_log_file_path
            file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8')
            file_handler.setFormatter(file_formatter)
            file_handler.addFilter(BlockLoggerFilter())  # 添加过滤器
            logger.addHandler(file_handler)

    # 在 logger 上绑定更新日志文件的函数
    logger.update_log_file = update_log_file

    # --- 添加区分消息和功能的函数 ---
    def info_msg(self, message, *args, **kwargs):
        if self.isEnabledFor(logging.INFO) and "INFO_MSG" not in _blocked_loggers:
            console_handler.setFormatter(console_formatter_msg)  # 设置消息格式
            self._log(logging.INFO, message, args, **kwargs)
            console_handler.setFormatter(console_formatter)  # 恢复默认格式

    def info_func(self, message, *args, **kwargs):
        if self.isEnabledFor(logging.INFO) and "INFO_FUNC" not in _blocked_loggers:
            console_handler.setFormatter(console_formatter_func)  # 设置功能格式
            self._log(logging.INFO, message, args, **kwargs)
            console_handler.setFormatter(console_formatter)  # 恢复默认格式

    # 将新函数绑定到 logger 类
    logging.Logger.info_msg = info_msg
    logging.Logger.info_func = info_func
    # --- 结束添加区分消息和功能的函数 ---

    _logger = logger


def get_logger(blocked_loggers=None):
    global _logger
    if _logger is None:
        createLogger(blocked_loggers)
    # 每次获取 logger 时检查是否需要更新日志文件
    _logger.update_log_file()
    return _logger

# app = Flask(__name__,static_folder="dist", static_url_path="",template_folder="dist")
app = Flask(__name__,static_folder="websources", static_url_path="",template_folder='websources')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # 只显示 ERROR 级别及以上的日志（隐藏 INFO 和 DEBUG）
logger=get_logger()
CORS(app,supports_credentials=True)  # 启用跨域支持
custom_git_path = os.path.join("environments", "MinGit", "cmd", "git.exe")
if os.path.exists(custom_git_path):
    git_path = custom_git_path
else:
    git_path = "git"
logger.info(f"Git path: {git_path}")

#默认用户信息
user_info = {
    "account":"eridanus",
    "password":"f6074ac37e2f8825367d9ae118a523abf16924a86414242ae921466db1e84583",
}

#用户信息文件
user_file = "./user_info.yaml"

#会话信息字典（token跟expires）
auth_info={}

#会话有效时长，秒数为单位（暂时只对webui生效）
auth_duration=720000
#可用的git源
REPO_SOURCES = [
   "https://ghfast.top/https://github.com/avilliai/Eridanus.git",
   "https://mirror.ghproxy.com/https://github.com/avilliai/Eridanus",
   "https://github.moeyy.xyz/https://github.com/avilliai/Eridanus",
   "https://github.com/avilliai/Eridanus.git",
   "https://gh.llkk.cc/https://github.com/avilliai/Eridanus.git",
   "https://gitclone.com/github.com/avilliai/Eridanus.git"
]

# 配置文件路径
def get_plugin_description(plugin_dir):
    init_file = os.path.join(plugin_dir, '__init__.py')
    if not os.path.exists(init_file):
        return None
    spec = importlib.util.spec_from_file_location("plugin_init", init_file)
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return getattr(module, 'plugin_description', None)
    except Exception:
        return None

def build_yaml_file_map(run_dir):
    yaml_map = {}
    run_dir = os.path.abspath(run_dir)
    for root, _, files in os.walk(run_dir):
        for file in files:
            if not file.endswith('.yaml'):
                continue
            abs_path = os.path.join(root, file)
            rel_path = os.path.relpath(abs_path, run_dir).replace("\\", "/")
            parts = rel_path.split("/")
            if len(parts) < 2:
                continue  # 不处理 run 目录下直接放的文件
            plugin_dir = os.path.join(run_dir, parts[0])
            plugin_desc = get_plugin_description(plugin_dir)
            if not plugin_desc:
                continue  # 没有 plugin_description 就跳过
            filename = os.path.splitext(parts[-1])[0]
            key = f"{plugin_desc}.{filename}"
            yaml_map[key] = abs_path
    return yaml_map
RUN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'run'))
YAML_FILES = build_yaml_file_map(RUN_DIR)

#鉴权
def auth(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        global auth_info
        recv_token = request.cookies.get('auth_token')
        # recv_expires = request.cookies.get('auth_expires')
        # print(f"客户端返回token：{recv_token}")
        try:
            if auth_info[recv_token] < int(time.time()):  #如果存在token且过期
                return jsonify({"error": "Unauthorized"}), 400
        except:     #不存在token
            return jsonify({"error": "Unauthorized"}), 400
        return func(*args, **kwargs)
    return wrapper

# 初始化 YAML 解析器（支持注释）
yaml = YAML()
yaml.preserve_quotes = True

"""
读取配置
"""

"""
新旧数据合并
"""

def merge_dicts(old, new):
    """
    递归合并旧数据和新数据。
    """
    for k, v in old.items():
        #print(f"处理 key: {k}, old value: {v} old type: {type(v)}, new value: {new.get(k)} new type: {type(new.get(k))}")
        # 如果值是一个字典，并且键在新的yaml文件中，那么我们就递归地更新键值对
        if isinstance(v, dict) and k in new and isinstance(new[k], dict):
            merge_dicts(v, new[k])
        # 如果值是列表，且新旧值都是列表，则合并并去重
        elif isinstance(v, list) and k in new and isinstance(new[k], list):
            # 合并列表并去重，保留旧列表顺序
            new[k] = [int(item) if isinstance(item, (str, ScalarString)) and item.lstrip('-').isdigit() else item for item in v if v is not None]
        elif k in new and type(v) != type(new[k]):

            if isinstance(new[k], DoubleQuotedScalarString) or isinstance(new[k], SingleQuotedScalarString):
                v = str(v)
                new[k] = v
            elif isinstance(new[k],ScalarInt) or isinstance(v, ScalarInt):
                v = int(v)
                new[k] = v
            else:
                #print(f"类型冲突 key: {k}, old value type: {type(v)}, new value type: {type(new[k])}")
                logger.warning(f"旧值: {v}, 新值: {new[k]} 直接覆盖")
                new[k] = v
        # 如果键在新的yaml文件中且类型一致，则更新值
        elif k in new:
            #print(f"更新 key: {k}, old value: {v}, new value: {new[k]}")
            new[k] = v
        # 如果键不在新的yaml中，直接添加
        else:
            pass
            #print(f"移除键 key: {k}, value: {v}")

def conflict_file_dealer(old_data: dict, file_new='new_aiReply.yaml'):
    logger.info(f"冲突文件处理: {file_new}")

    old_data_yaml_str = StringIO()
    yaml.dump(old_data, old_data_yaml_str)
    old_data_yaml_str.seek(0)  # 将光标移到字符串开头，以便后续读取

    # 将 YAML 字符串加载回 ruamel.yaml 对象
    old_data = yaml.load(old_data_yaml_str)
    # 加载新的YAML文件
    with open(file_new, 'r', encoding="utf-8") as file:
        new_data = yaml.load(file)

    # 遍历旧的YAML数据并更新新的YAML数据中的相应值
    merge_dicts(old_data, new_data)

    # 把新的YAML数据保存到新的文件中，保留注释
    with open(file_new, 'w', encoding="utf-8") as file:
        yaml.dump(new_data, file)
    return True

def extract_comments(data, path="", comments_dict=None):
    if comments_dict is None:
        comments_dict = {}

    if isinstance(data, comments.CommentedMap):
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            # 提取行尾注释
            if key in data.ca.items and data.ca.items[key][2]:
                comment = data.ca.items[key][2].value.strip("# \n")
                comments_dict[new_path] = comment
            # 递归处理子节点
            extract_comments(value, new_path, comments_dict)

    elif isinstance(data, comments.CommentedSeq):
        for index, item in enumerate(data):
            new_path = f"{path}[{index}]"
            # 序列整体注释（如果存在）
            if data.ca.comment and data.ca.comment[0]:
                comments_dict[path] = data.ca.comment[0].value.strip("# \n")
            # 递归处理子节点
            extract_comments(item, new_path, comments_dict)

    return comments_dict
def extract_key_order(data, path="", order_dict=None):
    if order_dict is None:
        order_dict = {}

    if isinstance(data, comments.CommentedMap):
        order_dict[path] = list(data.keys())  # 记录当前层级 key 的顺序
        for key, value in data.items():
            new_path = f"{path}.{key}" if path else key
            extract_key_order(value, new_path, order_dict)

    elif isinstance(data, comments.CommentedSeq):
        # 对于序列，记录其位置
        for index, item in enumerate(data):
            new_path = f"{path}[{index}]"
            extract_key_order(item, new_path, order_dict)

    return order_dict
def load_yaml_with_comments(file_path):

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)
        # 提取所有注释
        order = extract_key_order(data)
        comments = extract_comments(data)
        return {"data": data, "comments": comments,"order": order}
    except Exception as e:
        return {"error": str(e)}

def load_yaml(file_path):
    """加载 YAML 文件并返回内容及注释"""
    try:
        return load_yaml_with_comments(file_path)
    except Exception as e:
        return {"error": str(e)}

def save_yaml(file_path, data):
    """将数据保存回 YAML 文件"""

    #print(f"保存文件: {file_path}")
    #print(f"数据: {data}")
    return conflict_file_dealer(data["data"], file_path)


@app.route("/api/load/<filename>", methods=["GET"])
@auth
def load_file(filename):
    """加载指定的 YAML 文件"""
    if filename not in YAML_FILES:
        return jsonify({"error": "Invalid file name"}), 400

    file_path = YAML_FILES[filename]
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    data_with_comments = load_yaml(file_path)
    rtd=jsonify(data_with_comments)

    return rtd

@app.route("/api/save/<filename>", methods=["POST"])
@auth
def save_file(filename):
    """接收前端数据并保存到 YAML 文件"""
    if filename not in YAML_FILES:
        return jsonify({"error": "Invalid file name"}), 400

    file_path = YAML_FILES[filename]
    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404


    data = request.json  # 获取前端发送的 JSON 数据
    if not data:
        return jsonify({"error": "No data provided"}), 400

    result = save_yaml(file_path, data)
    if result is True:
        return jsonify({"message": "File saved successfully"})
    else:
        return jsonify(result), 500

@app.route("/api/sources", methods=["GET"])
@auth
def list_sources():
    """列出所有可用的git源"""
    return jsonify(list(REPO_SOURCES))

@app.route("/api/files", methods=["GET"])
@auth
def list_files():
    """列出所有可用的 YAML 文件"""
    return jsonify({"files": list(YAML_FILES.keys())})

@app.route("/api/pull", methods=["POST"])
@auth
def pull_eridanus():
    """从仓库拉取eridanus(未完成)"""
    return jsonify({"message": "success"})

@app.route("/api/clone", methods=["POST"])
@auth
def clone_source():
    data = request.get_json()
    source_url = data.get("source")

    if not source_url:
        return jsonify({"error": "Missing source URL"}), 400
    if os.path.exists("Eridanus"):
        return jsonify({"error": "Eridanus already exists。请删除现有Eridanus后再尝试克隆"}), 400

    logger.info_msg(f"开始克隆: {source_url}")
    os.system(f"{git_path} clone --depth 1 {source_url}")

    return jsonify({"message": f"开始部署 {source_url}"})
# 登录api
@app.route("/api/login", methods=['POST'])
def login():
    global auth_info
    global auth_duration
    data = request.get_json()
    logger.info_msg(data)
    if data == user_info:
        logger.info_msg("登录成功")
        auth_token = Fernet.generate_key().decode()      #生成token
        auth_expires = int(time.time()+auth_duration)    #生成过期时间
        auth_info[auth_token] = auth_expires             #加入字典
        logger.info_msg(auth_info)
        resp = make_response(jsonify({"message":"Success","auth_token": auth_token}))
        resp.set_cookie("auth_token", auth_token)
        resp.set_cookie("auth_expires",str(auth_expires))
        return resp
    else:
        logger.error("登录失败")
        return jsonify({"error": "Failed"}), 401

# 登出api
@app.route("/api/logout", methods=['GET','POST'])
def logout():
    global auth_info
    recv_token = request.cookies.get('auth_token')
    try:
        del auth_info[recv_token]
        logger.info_msg("用户登出")
        return jsonify({"message": "Success"})
    except:
        logger.error("token不存在")
        return jsonify({"error": "Invalid token"})

# 账户修改
@app.route("/api/profile", methods=['GET','POST'])
@auth
def profile():
    global user_info
    global auth_info
    if request.method == 'GET':
        return jsonify({"account": user_info['account']})
    elif request.method == 'POST':
        data = request.get_json()
        logger.info_msg(data)
        if data["account"]:
            user_info["account"] = data["account"]
        if data["password"]:
            user_info["password"] = data["password"]
            with open(user_file, 'w', encoding="utf-8") as file:
                yaml.dump(user_info, file)
        auth_info={}    #清空登录信息
        return jsonify({"message": "Success"})

@app.route("/")  # 定义根路由
def index():
    return redirect("./dashboard.html") # 返回 dashboard.html

@app.errorhandler(404)
def not_found(e):
    return send_from_directory(app.static_folder, 'index.html')

import base64

@app.route("/api/file2base64", methods=["POST"])
def file_to_base64():
    """将本地文件转换为 Base64 并返回"""
    data = request.json
    #print(data)
    file_path = data.get("path")
    logger.info_func(f"转换文件: {file_path}")
    if not file_path:
        return jsonify({"error": "Missing file path"}), 400

    if file_path.startswith("file://"):
        file_path = file_path[7:]  # 去掉 "file://"

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        with open(file_path, "rb") as file:
            base64_str = base64.b64encode(file.read()).decode("utf-8")

            file_extension = os.path.splitext(file_path)[1].lower()
            mime_types = {
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".png": "image/png",
                ".gif": "image/gif",
                ".mp3": "audio/mpeg",
                ".wav": "audio/wav",
                ".flac": "audio/flac",
                ".mp4": "video/mp4",
                ".webm": "video/webm",
                ".pdf": "application/pdf",
                ".zip": "application/zip",
                ".txt": "text/plain",
                ".json": "application/json",
            }

            mime_type = mime_types.get(file_extension)
            if not mime_type:
                return jsonify({"error": "Unsupported file type"}), 400

            return jsonify({"base64": f"data:{mime_type};base64,{base64_str}"})


    except Exception as e:
        return jsonify({"error": str(e)}), 500




if getattr(sys, 'frozen', False):  # 判断是否是 PyInstaller 打包的
    BASE_DIR = sys._MEIPASS  # PyInstaller 临时解压目录
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 普通运行环境

UPLOAD_FOLDER = os.path.join(BASE_DIR, "websources", "uploads")
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # 确保目录存在

@app.route("/api/move_file", methods=["POST"])
def move_file():
    """移动本地文件到可访问目录，并返回 URL"""
    data = request.json
    file_path = data.get("path")

    if not file_path:
        return jsonify({"error": "Missing file path"}), 400

    if file_path.startswith("file://"):
        file_path = file_path[7:]  # 去掉 "file://"

    if not os.path.exists(file_path):
        return jsonify({"error": "File not found"}), 404

    try:
        # 确保文件不会覆盖已有文件
        filename = os.path.basename(file_path)
        dest_path = os.path.join(UPLOAD_FOLDER, filename)

        logger.info_msg(f"目标路径: {dest_path} 原始路径: {file_path}")
        shutil.move(file_path, dest_path)  # 移动文件

        # 生成可访问的 URL
        relative_path = os.path.relpath(dest_path, app.static_folder)  # 计算相对路径
        file_url = f"/{relative_path}"  # Flask 已去掉 static_url_path，所以直接返回相对路径
        return jsonify({"url": file_url})

    except Exception as e:
        return jsonify({"error": str(e)}), 500
clients = set()

async def handle_connection(websocket):
    global auth_info
    logger.info_msg("WebSocket 客户端已连接")
    clients.add(websocket)

    try:
        # 发送连接成功消息
        #await websocket.send(json.dumps({'time': 1739849686, 'self_id': 3377428814, 'post_type': 'meta_event', 'meta_event_type': 'lifecycle', 'sub_type': 'connect'}))
        """while True:
            # 鉴权，超时抛出异常，终止websocket连接
            recv_token = await asyncio.wait_for(websocket.recv(),10)
            recv_token = json.loads(recv_token)['auth_token']
            try:
                if auth_info[recv_token] > int(time.time()):
                    print("WebSocket 客户端鉴权成功")
                    break
            except:
                raise ValueError"""

        while True:
            # 接收来自前端的消息
            message = await websocket.recv()
            logger.info_msg(f"收到前端消息: {message} {type(message)}")
            message = json.loads(message)
            if "echo" in message:
                for client in clients:
                    await client.send(json.dumps({'status': 'ok',
                                       'retcode': 0,
                                       'data': {'message_id': 1253451396},
                                       'message': '',
                                       'wording': '',
                                       'echo': message['echo']}))



            if isinstance(message,list):

                message.insert(0,{'type': 'at', 'data': {'qq': '1000000', 'name': 'Eridanus'}})

            #print(message, type(message))

            onebot_event = {
                'self_id': 1000000,
                'user_id': 111111111,
                'time': int(time.time()),
                'message_id': 1253451396,
                'real_id': 1253451396,
                'message_seq': 1253451396,
                'message_type': 'group',
                'sender':
                    {'user_id': 111111111, 'nickname': '主人', 'card': '', 'role': 'member', 'title': ''},
                'raw_message': "",
                'font': 14,
                'sub_type': 'normal',
                'message': message,
                'message_format': 'array',
                'post_type': 'message',
                'group_id': 879886836}

            event_json = json.dumps(onebot_event, ensure_ascii=False)

            # 发送给所有连接的客户端（后端）
            for client in clients:
                if client != websocket and "auth_token" not in message:  # 避免回传给前端
                    await client.send(event_json)


            logger.info_func(f"已发送 OneBot v11 事件: {event_json}")
    except websockets.exceptions.ConnectionClosed as e:
        logger.error(f"客户端连接关闭: {e}")
    except ValueError:
        logger.error("WebSocket 客户端鉴权失败")
    finally:
        logger.error("WebSocket 客户端断开连接")
        clients.remove(websocket)

# 启动 WebSocket 服务器
async def start_server():
    server = await websockets.serve(
        handle_connection,
        "0.0.0.0",
        5008,
        max_size=None  # 取消大小限制
    )

    logger.info_msg("WebSocket 服务端已启动，在 5008 端口监听...")
    await server.wait_closed()
def run_websocket_server():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(start_server())
    loop.run_forever()
def start_webui():
    # 初始化用户登录信息

    try:
        with open(user_file, 'r', encoding="utf-8") as file:
            yaml_file = yaml.load(file)
            user_info['account'] = yaml_file['account']
            user_info['password'] = yaml_file['password']
        logger.info_msg(f"用户登录信息读取成功。用户名：{user_info['account']} ")
    except:
        logger.error("用户登录信息读取失败，已恢复默认。默认用户名/密码均为 eridanus")
        with open(user_file, 'w', encoding="utf-8") as file:
            yaml.dump(user_info, file)

    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        server_thread = threading.Thread(target=run_websocket_server, daemon=True)
        server_thread.start()
        logger.info_msg("WebSocket 服务器已在后台运行")
    print("启动 webui")
    print("浏览器访问 http://localhost:5007")
    print("浏览器访问 http://localhost:5007")
    print("浏览器访问 http://localhost:5007")
    app.run(debug=True, host="0.0.0.0", port=5007)
#启动Eridanus并捕获输出，反馈到前端。
#不会写，不写！

if __name__ == "__main__":
    start_webui()