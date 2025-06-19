from flask import Flask, request, render_template, Response
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
import httpx
import json

app = Flask(__name__)

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

    def event_stream():
        yield f"data: 开始连接...\n\n"
        # 心跳包每2秒
        def heart():
            while not done[0]:
                now = time.strftime('%H:%M:%S')
                yield f"data: [心跳] {now}\n\n"
                time.sleep(2)
        from threading import Thread
        done = [False]
        heart_thread = Thread(target=lambda: [yield_ for yield_ in heart()])
        heart_thread.daemon = True
        heart_thread.start()

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(process_one, i, address, proxies[i], client_key) for i, address in enumerate(addresses)]
            for future in as_completed(futures):
                result = future.result()
                yield f"data: {result}\n\n"
        done[0] = True

    return Response(event_stream(), mimetype='text/event-stream')


def parse_proxy_line(proxy_line):
    # 忽略结尾 :SOCKS5
    proxy_line = proxy_line.strip()
    if proxy_line.upper().endswith(':SOCKS5'):
        proxy_line = proxy_line[:-7]
    parts = proxy_line.split(":")
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
    out = [f"🕐 [{i+1}] 使用代理：{proxy_url or '❌ 代理格式错误'}"]
    if not proxy_url:
        return "\n".join(out + ["❌ 无效代理格式，跳过"])
    task_id, result = create_yescaptcha_task(client_key, user_agent)
    out.append(f"打码任务ID: {task_id} 结果: {result}")
    if not task_id:
        return "\n".join(out + [f"❌ 打码任务创建失败: {result}"])
    solution, err = get_yescaptcha_result(client_key, task_id)
    out.append(f"打码结果: {solution} 错误: {err}")
    if not solution:
        return "\n".join(out + [f"❌ 打码失败: {err}"])
    claim_result = claim_water(address, solution, user_agent, proxy_url)
    # 提示txhash
    try:
        if isinstance(claim_result, str) and claim_result.startswith("{"):
            jr = json.loads(claim_result)
            if "msg" in jr and "Txhash" in jr["msg"]:
                out.append(f"✅ 领取成功: {jr['msg']}")
            else:
                out.append(f"❌ 领取失败: {jr.get('msg', claim_result)}")
        else:
            out.append(f"❌ 领取异常: {claim_result}")
    except Exception as e:
        out.append(f"❌ 领取异常: {claim_result}")
    return "\n".join(out)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)
