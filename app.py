from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor
import httpx, json, time

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
        return "缺少参数", 400
    if len(addresses) != len(proxies):
        return "地址和代理数不一致", 400

    def event_stream():
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_one, i+1, addr.strip(), proxies[i].strip(), client_key) for i, addr in enumerate(addresses)]
            for future in futures:
                result = future.result()
                yield f"data: {result}\n\n"

    return Response(event_stream(), mimetype='text/event-stream')

def parse_proxy(proxy_line):
    parts = proxy_line.strip().split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        return f"socks5://{user}:{pwd}@{host}:{port}"
    return None

def create_captcha_task(client_key, user_agent):
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
        return r.json().get("taskId"), r.text
    except Exception as e:
        return None, str(e)

def get_captcha_result(client_key, task_id, timeout=120):
    start = time.time()
    while time.time() - start < timeout:
        try:
            r = httpx.post("https://api.yescaptcha.com/getTaskResult", json={"clientKey": client_key, "taskId": task_id}, timeout=30)
            data = r.json()
            if data.get("status") == "ready":
                return data["solution"]["gRecaptchaResponse"], None
        except Exception as e:
            return None, str(e)
        time.sleep(3)
    return None, "打码超时"

def claim_water(address, captcha_token, user_agent, proxy_url):
    try:
        with httpx.Client(proxies={"all://": proxy_url}, timeout=60) as client:
            r = client.post("https://faucet-go-production.up.railway.app/api/claim", json={"address": address}, headers={
                "h-captcha-response": captcha_token,
                "user-agent": user_agent,
                "content-type": "application/json"
            })
            return r.text
    except Exception as e:
        return f"请求失败: {e}"

def process_one(i, address, proxy_line, client_key):
    proxy_url = parse_proxy(proxy_line)
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

    msg = f"🕐 [{i}] 使用代理：{proxy_url}\n"

    task_id, res = create_captcha_task(client_key, user_agent)
    if not task_id:
        return msg + f"❌ 打码任务创建失败：{res}"

    solution, err = get_captcha_result(client_key, task_id)
    if not solution:
        return msg + f"❌ 打码失败：{err}"

    faucet_result = claim_water(address, solution, user_agent, proxy_url)
    return msg + f"✅ [{i}] {address} 完成领取\n{faucet_result}"
