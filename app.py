from flask import Flask, render_template, request, Response
from concurrent.futures import ThreadPoolExecutor
import requests, time, queue

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/run_stream")
def run_stream():
    addresses = request.args.get('addresses', '').strip().splitlines()
    proxies = request.args.get('proxies', '').strip().splitlines()
    client_key = request.args.get('client_key', '').strip()

    if not (addresses and proxies and client_key):
        return Response("data: ❌ 参数缺失\n\n", mimetype='text/event-stream')
    if len(addresses) != len(proxies):
        return Response("data: ❌ 地址和代理数量不一致\n\n", mimetype='text/event-stream')

    website_url = "https://faucet.campnetwork.xyz/"
    website_key = "5b86452e-488a-4f62-bd32-a332445e2f51"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

    def parse_proxy_line(proxy_line):
        parts = proxy_line.strip().split(":")
        if len(parts) == 4:
            host, port, user, pwd = parts
            proxy_url = f"http://{user}:{pwd}@{host}:{port}"
            return {"http": proxy_url, "https": proxy_url}
        return None

    def create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies=None):
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
            resp = requests.post("https://api.yescaptcha.com/createTask", json=payload, proxies=proxies, timeout=60)
            data = resp.json()
            return data.get("taskId"), data
        except Exception as e:
            return None, f"创建打码任务失败: {e}"

    def get_yescaptcha_result(client_key, task_id, proxies=None, timeout=120):
        payload = {"clientKey": client_key, "taskId": task_id}
        start_time = time.time()
        while True:
            try:
                resp = requests.post("https://api.yescaptcha.com/getTaskResult", json=payload, proxies=proxies, timeout=60).json()
                if resp.get("errorId") != 0:
                    return None, resp.get("errorDescription")
                if resp.get("status") == "ready":
                    return resp["solution"]["gRecaptchaResponse"], None
            except Exception as e:
                return None, f"获取打码结果失败: {e}"
            if time.time() - start_time > timeout:
                return None, "识别超时"
            time.sleep(3)

    def claim_water(address, hcaptcha_response, user_agent, proxies=None):
        url = "https://faucet-go-production.up.railway.app/api/claim"
        headers = {
            "h-captcha-response": hcaptcha_response,
            "user-agent": user_agent,
            "content-type": "application/json"
        }
        payload = {"address": address}
        try:
            resp = requests.post(url, json=payload, headers=headers, proxies=proxies, timeout=60)
            return resp.text
        except Exception as e:
            return f"领水请求失败: {e}"

    def task_worker(index, address, proxy_line, q):
        proxies = parse_proxy_line(proxy_line)
        q.put(f"{index+1}. 🕐 开始处理：{address}")

        task_id, msg = create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies)
        if not task_id:
            q.put(f"{index+1}. ❌ 创建打码任务失败：{msg}")
            return
        result, err = get_yescaptcha_result(client_key, task_id, proxies)
        if not result:
            q.put(f"{index+1}. ❌ 打码失败：{err}")
            return
        claim_result = claim_water(address, result, user_agent, proxies)
        q.put(f"{index+1}. ✅ {address}：{claim_result}")

    def generate_stream():
        q = queue.Queue()
        with ThreadPoolExecutor(max_workers=10) as executor:
            for i in range(len(addresses)):
                executor.submit(task_worker, i, addresses[i], proxies[i], q)

            finished = 0
            total = len(addresses)
            while finished < total:
                try:
                    message = q.get(timeout=180)
                    yield f"data: {message}\n\n"
                    if "✅" in message or "❌" in message:
                        finished += 1
                except queue.Empty:
                    break
        yield "data: 🎉 所有任务完成\n\n"

    return Response(generate_stream(), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=True, threaded=True)
