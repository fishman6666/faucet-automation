from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import json
from httpx_socks import SyncProxyTransport

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run')
def run():
    addresses = request.args.get('addresses', '').strip().splitlines()
    proxies = request.args.get('proxies', '').strip().splitlines()
    client_key = request.args.get('client_key', '').strip()

    if not (addresses and proxies and client_key):
        return "参数缺失", 400
    if len(addresses) != len(proxies):
        return "地址和代理数量不一致", 400

    def event_stream():
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_one, i, addr, proxies[i], client_key) for i, addr in enumerate(addresses)]
            for future in futures:
                result = future.result()
                yield f"data: {result}\n\n"

    return Response(event_stream(), mimetype='text/event-stream')


def parse_proxy_line(proxy_line):
    parts = proxy_line.strip().split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
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
    url = "https://faucet.campnetwork.xyz/api/claim"
    headers = {
        "h-captcha-response": hcaptcha_response,
        "user-agent": user_agent,
        "content-type": "application/json"
    }
    payload = {"address": address}
    try:
        transport = SyncProxyTransport.from_url(proxy_url)
        with httpx.Client(transport=transport, timeout=60) as client:
            resp = client.post(url, headers=headers, json=payload)
            return resp.text
    except Exception as e:
        return f"请求失败: {e}"


def process_one(i, address, proxy_line, client_key):
    proxy_url = parse_proxy_line(proxy_line)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

    yield_msg = f"🕐 [{i+1}] 使用代理：{proxy_url}\n"

    task_id, result = create_yescaptcha_task(client_key, user_agent)
    if not task_id:
        return yield_msg + f"❌ 打码任务创建失败: {result}\n"

    solution, err = get_yescaptcha_result(client_key, task_id)
    if not solution:
        return yield_msg + f"❌ 打码失败: {err}\n"

    result = claim_water(address, solution, user_agent, proxy_url)
    return yield_msg + f"✅ [{i+1}] {address} 完成领取\n{result}\n"

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
