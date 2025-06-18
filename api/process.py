import json
import base64
from concurrent.futures import ThreadPoolExecutor, as_completed

from openpyxl import Workbook

from flask import Request, jsonify

def parse_proxy_line(proxy_line):
    parts = proxy_line.strip().split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies=None):
    import requests
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
    import time, requests
    url = "https://api.yescaptcha.com/getTaskResult"
    payload = {"clientKey": client_key, "taskId": task_id}
    start_time = time.time()
    while True:
        try:
            resp = requests.post(url, json=payload, proxies=proxies, timeout=60).json()
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
    import requests
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

def process_one(index, address, proxy_line, client_key, website_url, website_key, user_agent):
    proxies = parse_proxy_line(proxy_line)
    task_id, create_resp = create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies=proxies)
    if not task_id:
        return {"index": index, "address": address, "proxy": proxy_line, "status": "❌ 创建任务失败", "info": str(create_resp)}
    hcaptcha_response, err = get_yescaptcha_result(client_key, task_id, proxies=proxies)
    if not hcaptcha_response:
        return {"index": index, "address": address, "proxy": proxy_line, "status": "❌ 打码失败", "info": str(err)}
    result = claim_water(address, hcaptcha_response, user_agent, proxies=proxies)
    return {"index": index, "address": address, "proxy": proxy_line, "status": "✅ 成功", "info": result}

def handler(request: Request):
    body = request.get_json()
    addresses = body.get("addresses", [])
    proxies = body.get("proxies", [])
    client_key = body.get("client_key", "")

    if not (addresses and proxies and client_key):
        return jsonify({"error": "参数缺失"})

    if len(addresses) != len(proxies):
        return jsonify({"error": "地址和代理数量不一致"})

    website_url = "https://faucet.campnetwork.xyz/"
    website_key = "5b86452e-488a-4f62-bd32-a332445e2f51"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

    results = []
    with ThreadPoolExecutor(max_workers=20) as executor:
        futures = [
            executor.submit(process_one, idx, addr, proxies[idx], client_key, website_url, website_key, user_agent)
            for idx, addr in enumerate(addresses)
        ]
        for future in as_completed(futures):
            results.append(future.result())

    return jsonify({"results": sorted(results, key=lambda x: x["index"])})
