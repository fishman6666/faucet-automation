from flask import Flask, render_template, request, Response, stream_with_context
from concurrent.futures import ThreadPoolExecutor
import requests
import time
import httpx

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
        return "❌ 参数缺失", 400
    if len(addresses) != len(proxies):
        return "❌ 地址和代理数量不一致", 400

    website_url = "https://faucet.campnetwork.xyz/"
    website_key = "5b86452e-488a-4f62-bd32-a332445e2f51"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

    def parse_proxy(proxy_line):
        parts = proxy_line.strip().split(":")
        if len(parts) == 4:
            host, port, user, pwd = parts
            return f"socks5://{user}:{pwd}@{host}:{port}"
        return None

    def event_stream():
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = []
            for i, address in enumerate(addresses):
                proxy_url = parse_proxy(proxies[i])
                futures.append(executor.submit(process_one, i, address, proxy_url))

            for future in futures:
                result = future.result()
                yield f"data: {result}\n\n"
                time.sleep(0.5)

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')


def create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxy=None):
    payload = {
        "clientKey": client_key,
        "task": {
            "type": "HCaptchaTaskProxyless",
            "websiteURL": website_url,
            "websiteKey": website_key,
            "userAgent": user_agent
        }
    }
    try:
        with httpx.Client(proxies=proxy, timeout=60) as client:
            resp = client.post("https://api.yescaptcha.com/createTask", json=payload)
        data = resp.json()
        return data.get("taskId"), data
    except Exception as e:
        return None, f"创建打码任务失败: {e}"


def get_yescaptcha_result(client_key, task_id, proxy=None, timeout=120):
    payload = {"clientKey": client_key, "taskId": task_id}
    start = time.time()
    while True:
        try:
            with httpx.Client(proxies=proxy, timeout=60) as client:
                resp = client.post("https://api.yescaptcha.com/getTaskResult", json=payload)
            resp_json = resp.json()
            if resp_json.get("errorId") != 0:
                return None, resp_json.get("errorDescription")
            if resp_json.get("status") == "ready":
                return resp_json["solution"]["gRecaptchaResponse"], None
        except Exception as e:
            return None, f"获取打码结果失败: {e}"
        if time.time() - start > timeout:
            return None, "识别超时"
        time.sleep(3)


def claim_water(address, hcaptcha_response, user_agent, proxy=None):
    url = "https://faucet-go-production.up.railway.app/api/claim"
    headers = {
        "h-captcha-response": hcaptcha_response,
        "user-agent": user_agent,
        "content-type": "application/json"
    }
    payload = {"address": address}
    try:
        with httpx.Client(proxies=proxy, timeout=60) as client:
            resp = client.post(url, json=payload, headers=headers)
        return resp.text
    except Exception as e:
        return f"领水请求失败: {e}"


def process_one(index, address, proxy):
    task_id, msg = create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxy)
    if not task_id:
        return f"{index+1}. ❌ 创建任务失败：{msg}"
    result, err = get_yescaptcha_result(client_key, task_id, proxy)
    if not result:
        return f"{index+1}. ❌ 打码失败：{err}"
    claim_result = claim_water(address, result, user_agent, proxy)
    return f"{index+1}. ✅ {address}：{claim_result}"


if __name__ == '__main__':
    app.run(debug=True)
