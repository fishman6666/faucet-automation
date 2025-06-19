from flask import Flask, request, render_template, jsonify
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import json
import threading
import os

app = Flask(__name__)
LOG_FILE = "claim_results.jsonl"
log_lock = threading.Lock()

def save_result_log(result: dict):
    with log_lock:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(result, ensure_ascii=False) + "\n")

def load_result_log():
    if not os.path.exists(LOG_FILE):
        return []
    with log_lock:
        with open(LOG_FILE, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run', methods=["POST"])
def run():
    addresses_raw = request.form.get('addresses', '')
    proxies_raw = request.form.get('proxies', '')
    client_key = request.form.get('client_key', '').strip()

    addresses = [a.strip() for a in addresses_raw.strip().split('\n') if a.strip()]
    proxies = [p.strip() for p in proxies_raw.strip().split('\n') if p.strip()]

    if not (addresses and proxies and client_key):
        return "❌ 参数缺失，请确保地址、代理和 clientKey 都填写", 400
    if len(addresses) != len(proxies):
        return "❌ 地址数量与代理数量不一致", 400

    def parse_proxy_line(proxy_line):
        parts = proxy_line.strip().split(":")
        if len(parts) >= 4:
            host, port, user, pwd = parts[:4]
            return f"socks5://{user}:{pwd}@{host}:{port}"
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
        status_msg = f"🕐 [{i+1}] 使用代理：{proxy_url or '❌ 代理格式错误'}"
        result_data = {
            "index": i+1,
            "address": address,
            "proxy": proxy_url or proxy_line,
            "success": False,
            "msg": status_msg,
            "txhash": None
        }

        if not proxy_url:
            result_data["msg"] += " ❌ 无效代理格式，跳过"
            save_result_log(result_data)
            return result_data

        task_id, result = create_yescaptcha_task(client_key, user_agent)
        if not task_id:
            result_data["msg"] += f" ❌ 打码任务创建失败: {result}"
            save_result_log(result_data)
            return result_data

        solution, err = get_yescaptcha_result(client_key, task_id)
        if not solution:
            result_data["msg"] += f" ❌ 打码失败: {err}"
            save_result_log(result_data)
            return result_data

        claim_result = claim_water(address, solution, user_agent, proxy_url)
        if "Txhash" in claim_result:
            txhash = claim_result.split("Txhash: ")[-1].strip('"}\n ')
            result_data["success"] = True
            result_data["txhash"] = txhash
            result_data["msg"] += f" 🎉 领取成功！Txhash: {txhash}"
        else:
            result_data["msg"] += f" ❌ 领取失败：{claim_result}"

        save_result_log(result_data)
        return result_data

    results = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [
            executor.submit(process_one, i, addr, proxies[i], client_key)
            for i, addr in enumerate(addresses)
        ]
        for f in futures:
            results.append(f.result())

    return jsonify({"results": results})

@app.route('/history')
def history():
    return jsonify({"results": load_result_log()})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
