from flask import Flask, render_template, request
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests, time

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run', methods=['POST'])
def run():
    addresses = request.form.get('addresses', '').strip().splitlines()
    proxies = request.form.get('proxies', '').strip().splitlines()
    client_key = request.form.get('client_key', '').strip()

    if not (addresses and proxies and client_key):
        return "❌ 参数缺失", 400
    if len(addresses) != len(proxies):
        return "❌ 地址和代理数量不一致", 400

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
            return None, str(e)

    def get_yescaptcha_result(client_key, task_id, proxies=None, timeout=120):
        payload = {"clientKey": client_key, "taskId": task_id}
        start_time = time.time()
        while True:
            try:
                resp = requests.post("https://api.yescaptcha.com/getTaskResult", json=payload, proxies=proxies, timeout=60).json()
                if resp.get("status") == "ready":
                    return resp["solution"]["gRecaptchaResponse"], None
            except Exception as e:
                return None, str(e)
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
            return str(e)

    def process_one(index, address, proxy_line):
        proxies = parse_proxy_line(proxy_line)
        task_id, msg = create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies)
        if not task_id:
            return f"{index+1}. ❌ 创建任务失败：{msg}"
        result, err = get_yescaptcha_result(client_key, task_id, proxies)
        if not result:
            return f"{index+1}. ❌ 打码失败：{err}"
        claim_result = claim_water(address, result, user_agent, proxies)
        return f"{index+1}. ✅ {address}：{claim_result}"

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [
            executor.submit(process_one, i, addr, proxies[i])
            for i, addr in enumerate(addresses)
        ]
        for f in as_completed(futures):
            results.append(f.result())

    return "<br>".join(results)

if __name__ == "__main__":
    app.run(debug=True)
