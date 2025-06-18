import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from openpyxl import Workbook
import base64
import json

def parse_proxy_line(proxy_line):
    parts = proxy_line.strip().split(":")
    if len(parts) == 4:
        host, port, user, pwd = parts
        proxy_url = f"http://{user}:{pwd}@{host}:{port}"
        return {"http": proxy_url, "https": proxy_url}
    return None

def create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies=None):
    url = "https://api.yescaptcha.com/createTask"
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
        resp = requests.post(url, json=payload, proxies=proxies, timeout=60)
        data = resp.json()
        return data.get("taskId"), data
    except Exception as e:
        return None, f"代理请求异常: {e}"

def get_yescaptcha_result(client_key, task_id, proxies=None, timeout=120):
    url = "https://api.yescaptcha.com/getTaskResult"
    payload = {
        "clientKey": client_key,
        "taskId": task_id
    }
    start_time = time.time()
    try:
        while True:
            try:
                resp = requests.post(url, json=payload, proxies=proxies, timeout=60).json()
            except Exception as e:
                return None, f"代理请求异常: {e}"
            if resp.get("errorId") != 0:
                return None, resp.get("errorDescription")
            if resp.get("status") == "ready":
                solution = resp["solution"]
                return solution["gRecaptchaResponse"], None
            if time.time() - start_time > timeout:
                return None, "识别超时"
            time.sleep(3)
    except Exception as e:
        return None, f"代理请求异常: {e}"

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
        return f"请求异常: {e}"

def handler(request):
    body = request.get_json()
    addresses = body.get("addresses", [])
    proxies_list = body.get("proxies", [])
    client_key = body.get("client_key")
    website_url = "https://faucet.campnetwork.xyz/"
    website_key = "5b86452e-488a-4f62-bd32-a332445e2f51"
    user_agent = body.get("user_agent", "Mozilla/5.0")

    results = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_index = {
            executor.submit(process_one, idx, addr, proxies_list[idx], client_key, website_url, website_key, user_agent): idx
            for idx, addr in enumerate(addresses)
        }
        for future in as_completed(future_to_index):
            res = future.result()
            results.append(res)

    # 生成 Excel 到内存
    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "地址", "代理", "状态", "返回内容"])
    for row in sorted(results, key=lambda x: x[0]):
        ws.append(row)

    from io import BytesIO
    output = BytesIO()
    wb.save(output)
    excel_data = output.getvalue()
    output.close()

    encoded_excel = base64.b64encode(excel_data).decode()
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"file": encoded_excel})
    }

def process_one(index, address, proxy_line, client_key, website_url, website_key, user_agent):
    proxies = parse_proxy_line(proxy_line)
    task_id, create_resp = create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies=proxies)
    if not task_id:
        return (index, address, proxy_line, "打码任务创建失败", str(create_resp))
    hcaptcha_response, err = get_yescaptcha_result(client_key, task_id, proxies=proxies)
    if not hcaptcha_response:
        return (index, address, proxy_line, "打码失败", str(err))
    claim_result = claim_water(address, hcaptcha_response, user_agent, proxies=proxies)
    return (index, address, proxy_line, "成功", claim_result)

