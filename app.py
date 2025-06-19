from flask import Flask, request, render_template, Response, jsonify
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import threading
from queue import Queue, Empty
import json
import re
import os

app = Flask(__name__)

HISTORY_FILE = "results.txt"

def save_history(line):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(line.replace('\n', ' ') + "\n")

def read_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return [line.strip() for line in f if line.strip()]

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run')
def run():
    addresses_raw = request.args.get('addresses', '')
    proxies_raw = request.args.get('proxies', '')
    client_key = request.args.get('client_key', '').strip()
    addresses = [a.strip() for a in addresses_raw.strip().split('\n') if a.strip()]
    proxies = [p.strip() for p in proxies_raw.strip().split('\n') if p.strip()]
    if not (addresses and proxies and client_key):
        return "❌ 参数缺失，请确保地址、代理和 clientKey 都填写", 400
    if len(addresses) != len(proxies):
        return "❌ 地址数量与代理数量不一致", 400

    def event_stream():
        q = Queue()
        def task_worker():
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = [executor.submit(process_one, i, address, proxies[i], client_key) for i, address in enumerate(addresses)]
                for future in futures:
                    try:
                        result = future.result()
                    except Exception as e:
                        result = f"❌ 后台异常: {e}"
                    q.put(result)
            q.put(None)
        threading.Thread(target=task_worker, daemon=True).start()
        last_heartbeat = time.time()
        while True:
            try:
                result = q.get(timeout=5)
                if result is None:
                    break
                yield f"data: {result}\n\n"
            except Empty:
                # 心跳包每5秒
                yield f"data: [心跳] {time.strftime('%H:%M:%S')}\n\n"
    return Response(event_stream(), mimetype='text/event-stream')

@app.route("/results")
def get_results():
    return jsonify(read_history())

def parse_proxy_line(proxy_line):
    try:
        parts = proxy_line.strip().split(":")
        if len(parts) == 5 and parts[-1].upper() == "SOCKS5":
            host, port, user, pwd, _ = parts
        elif len(parts) == 4:
            host, port, user, pwd = parts
        else:
            return None
        return f"socks5://{user}:{pwd}@{host}:{port}"
    except Exception:
        return None

def create_yescaptcha_task(client_key, user_agent):
    payload = {
        "clientKey": client_key,
        "task": {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": "https://faucet.campnetwork.xyz/",
            "websiteKey": "5b86452e-488a-4f62-bd32-a332445e2f51",
            "userAgent": user_agent
        }
    }
    try:
        r = httpx.post("https://api.yescaptcha.com/createTask", json=payload, timeout=60)
        r.raise_for_status()
        task_id = r.json().get("taskId")
        return task_id, r.json()
    except Exception as e:
        return None, {"error": str(e)}

def get_yescaptcha_result(client_key, task_id, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        try:
            resp = httpx.post("https://api.yescaptcha.com/getTaskResult", json={"clientKey": client_key, "taskId": task_id}, timeout=60)
            result = resp.json()
            if result.get("status") == "ready":
                return result['solution']['gRecaptchaResponse'], None
        except Exception as e:
            return None, str(e)
        time.sleep(3)
    return None, "打码超时"

def claim_water(address, hcaptcha_response, user_agent, proxy_url):
    url = "https://faucet-go-production.up.railway.app/api/claim"
    headers = {
        "h-captcha-response": hcaptcha_response,
        "user-agent": user_agent,
        "content-type": "application/json"
    }
    payload = {"address": address}
    try:
        with httpx.Client(proxies=proxy_url, timeout=60) as client:
            resp = client.post(url, headers=headers, json=payload)
            return resp.text
    except Exception as e:
        return f"请求失败: {e}"

def process_one(i, address, proxy_line, client_key):
    proxy_url = parse_proxy_line(proxy_line)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    if not proxy_url:
        fail = f"❌ {address} 代理格式错误"
        save_history(fail)
        return fail

    task_id, result = create_yescaptcha_task(client_key, user_agent)
    if not task_id:
        fail = f"❌ {address} 打码失败"
        save_history(fail)
        return fail

    solution, err = get_yescaptcha_result(client_key, task_id)
    if not solution:
        fail = f"❌ {address} 打码无解: {err}"
        save_history(fail)
        return fail

    claim_result = claim_water(address, solution, user_agent, proxy_url)
    # 判断是否领取成功
    if isinstance(claim_result, str) and '"msg":"Txhash:' in claim_result.replace(" ", ""):
        try:
            obj = json.loads(claim_result)
            tx = obj["msg"].split("Txhash:")[-1].strip()
        except Exception:
            m = re.search(r'Txhash[:：]([0-9a-fA-Fx]+)', claim_result)
            tx = m.group(1) if m else ""
        succ = f"🎉 {address} 领取成功！Txhash: <span class='txhash'>{tx}</span>"
        save_history(succ)
        return succ
    else:
        fail = f"❌ {address} 失败，可重试：{claim_result}"
        save_history(fail)
        return fail

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
