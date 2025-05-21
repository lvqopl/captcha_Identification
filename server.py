from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from datetime import datetime
# from utils import get_offset
from collections import defaultdict
import ddddocr
import base64
import os
import json
import cv2
import numpy as np

app = Flask(__name__)
CORS(app)

# 用于存储 IP 访问计数
ip_counter = defaultdict(int)

ocr = ddddocr.DdddOcr()

# 简单的本地路径缓存文件
PATH_DB_FILE = "path_db.json"
LOG_DIR = "./logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 加载路径记录
def load_path_db():
    if os.path.exists(PATH_DB_FILE):
        with open(PATH_DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

# 保存路径记录
def save_path_db(data):
    with open(PATH_DB_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

path_db = load_path_db()

def get_offset(bg_bytes, target_bytes):
    """识别滑动验证码缺口位置（返回 x 坐标）"""
    bg_array = np.frombuffer(bg_bytes, np.uint8)
    target_array = np.frombuffer(target_bytes, np.uint8)

    bg_img = cv2.imdecode(bg_array, cv2.IMREAD_COLOR)
    target_img = cv2.imdecode(target_array, cv2.IMREAD_COLOR)

    result = cv2.matchTemplate(bg_img, target_img, cv2.TM_CCOEFF_NORMED)
    min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)

    x, y = max_loc
    return x, y  # 返回滑块应滑动的横坐标
# 添加限流器：使用访问者 IP 地址作为识别方式
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["100 per hour"],  # 默认每 IP 每小时最多请求 100 次
)

@app.route('/')
def index():
    ip = request.remote_addr
    ip_counter[ip] += 1

    # 返回一个简单的 HTML 页面
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>IP 访问统计</title>
        <meta charset="utf-8">
        <style>
            body { font-family: Arial, sans-serif; padding: 20px; }
            table { border-collapse: collapse; width: 50%; }
            th, td { border: 1px solid #ccc; padding: 8px; text-align: left; }
        </style>
    </head>
    <body>
        <h2>访问者 IP 统计</h2>
        <table>
            <tr><th>IP 地址</th><th>访问次数</th></tr>
            {% for ip, count in stats.items() %}
            <tr><td>{{ ip }}</td><td>{{ count }}</td></tr>
            {% endfor %}
        </table>
    </body>
    </html>
    """
    return render_template_string(html, stats=dict(ip_counter))

# ✅ /cssPath?href=https://some.site/page
@app.route('/cssPath', methods=['GET'])
@limiter.limit("60 per minute")
def get_css_path():
    href = request.args.get("href", "").split("?")[0]
    if not href:
        return jsonify({"success": False, "msg": "缺少 href 参数"}), 400

    record = path_db.get(href)
    if record:
        best_path = max(record.items(), key=lambda x: x[1])  # 找出次数最多的 path
        return jsonify({
            "success": True,
            "path": best_path[0],
            "recommendTimes": best_path[1]
        })
    else:
        return jsonify({"success": True, "path": None, "recommendTimes": 0})

@app.route('/captcha', methods=['POST'])
@limiter.limit("30 per minute")
def recognize_captcha():
    file = request.files.get("img")
    detail_raw = request.form.get("detail", "{}")

    try:
        detail = json.loads(detail_raw)
    except Exception as e:
        detail = {}

    if not file:
        return jsonify({"success": False, "msg": "No image uploaded"}), 400

    try:
        img_bytes = file.read()
        code = ocr.classification(img_bytes)
    except Exception as e:
        return jsonify({"success": False, "msg": "OCR failed", "error": str(e)}), 500

    # 记录路径统计
    href = detail.get("href", "").split("?")[0]
    path = detail.get("path", "")
    if href and path:
        path_db.setdefault(href, {})
        path_db[href][path] = path_db[href].get(path, 0) + 1
        save_path_db(path_db)

    # 日志记录
    log_data = {
        "code": code,
        "path": path,
        "src": detail.get("src"),
        "href": href,
        "host": detail.get("host"),
        "timestamp": datetime.now().isoformat()
    }

    try:
        log_file = os.path.join(LOG_DIR, "recognition_log.jsonl")
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[⚠️日志写入失败]", e)

    return jsonify({
        "success": True,
        "data": {
            "code": code,
            "detail": log_data
        }
    })


# # ✅ /captcha 识别接口（支持 path 上报）
# @app.route('/captcha', methods=['POST'])
# @limiter.limit("30 per minute")
# def recognize_captcha():
#     file = request.files.get("img")
#     detail_raw = request.form.get("detail", "{}")
#     try:
#         detail = json.loads(detail_raw)
#     except Exception as e:
#         detail = {}
#     if not file:
#         return jsonify({"success": False, "msg": "No image uploaded"}), 400
#
#     try:
#         code = ocr.classification(file.read())
#     except Exception as e:
#         return jsonify({"success": False, "msg": "OCR failed", "error": str(e)}), 500
#
#     # ✅ 日志记录（建议做）
#     log_data = {
#         "code": code,
#         "path": detail.get("path"),
#         "src": detail.get("src"),
#         "href": detail.get("href"),
#         "host": detail.get("host"),
#         "timestamp": datetime.now().isoformat()
#     }
#
#     try:
#         log_file = os.path.join(LOG_DIR, "recognition_log.jsonl")
#         with open(log_file, "a", encoding="utf-8") as f:
#             f.write(json.dumps(log_data, ensure_ascii=False) + "\n")
#     except Exception as e:
#         print("[⚠️日志写入失败]", e)
#
#     return jsonify({
#         "success": True,
#         "data": {
#             "code": code,
#             "detail": log_data
#         }
#     })
#
#     path = request.form.get("path", "")
#     src = request.form.get("src", "")
#     href = request.headers.get("Referer", "").split("?")[0]
#
#     if not file:
#         return jsonify({"success": False, "msg": "未上传图片"}), 400
#
#     try:
#         code = ocr.classification(file.read())
#     except Exception as e:
#         return jsonify({"success": False, "msg": "识别失败", "error": str(e)}), 500
#
#     # 记录路径使用次数
#     if path and href:
#         path_db.setdefault(href, {})
#         path_db[href][path] = path_db[href].get(path, 0) + 1
#         save_path_db(path_db)
#
#     return jsonify({
#         "success": True,
#         "data": {
#             "code": code,
#             "path": path,
#             "src": src
#         }
#     })

@app.route('/ocr', methods=['POST'])
def recognize_ocr():
    data = request.get_json()
    image_base64 = data.get("image")
    detail = data.get("detail", {})

    if not image_base64:
        return jsonify({"success": False, "msg": "No image"}), 400

    try:
        img_bytes = base64.b64decode(image_base64.split(",")[-1])
        code = ocr.classification(img_bytes)
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500

    # 可选：记录日志
    with open("logs/ocr_log.jsonl", "a", encoding="utf-8") as f:
        log = {
            "code": code,
            "detail": detail,
            "time": datetime.now().isoformat()
        }
        f.write(json.dumps(log, ensure_ascii=False) + "\n")

    return jsonify({"success": True, "data": {"code": code}})

@app.route('/slideCaptcha', methods=['POST'])
def slide_captcha():
    try:
        bg_img = request.files.get('bg_img')
        target_img = request.files.get('target_img')
        target_width = int(request.form.get("targetWidth", 0))
        bg_width = int(request.form.get("bgWidth", 0))
        detail = request.form.get("detail", "{}")

        if not bg_img or not target_img:
            return jsonify({"success": False, "msg": "缺少图片"}), 400

        bg_bytes = bg_img.read()
        target_bytes = target_img.read()

        x, y = get_offset(bg_bytes, target_bytes)

        # 比例换算（如果前端传了原始宽度）
        if bg_width and target_width:
            scale = target_width / bg_width
            x = int(x * scale)

        return jsonify({
            "success": True,
            "data": {
                "target": [x, y],
                "timestamp": datetime.now().isoformat()
            }
        })
    except Exception as e:
        return jsonify({"success": False, "msg": str(e)}), 500

@app.route('/')
def hello():
    return "🧠 验证码识别服务运行中！"

@app.route('/jwocr', methods=['POST'])
def recognize():
    try:
        data = request.get_json()
        img_base64 = data.get("image")
        img_bytes = base64.b64decode(img_base64)
        result = ocr.classification(img_bytes)
        print(result)
        return jsonify({"success": True, "text": result})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7000)

