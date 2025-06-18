import json
import time
from io import BytesIO
from openpyxl import Workbook
import requests

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

def process_one(index, address, proxy_line, client_key, website_url, website_key, user_agent):
    proxies = parse_proxy_line(proxy_line)
    # 1. 创建打码任务
    task_id, create_resp = create_yescaptcha_task(client_key, website_url, website_key, user_agent, proxies=proxies)
    if not task_id:
        return (index, address, proxy_line, "打码任务创建失败", str(create_resp))
    # 2. 获取打码结果
    hcaptcha_response, err = get_yescaptcha_result(client_key, task_id, proxies=proxies)
    if not hcaptcha_response:
        return (index, address, proxy_line, "打码失败", str(err))
    # 3. 领水
    claim_result = claim_water(address, hcaptcha_response, user_agent, proxies=proxies)
    return (index, address, proxy_line, "成功", claim_result)

def main(event, context):
    import cgi
    from io import BytesIO

    content_type = event['headers'].get('content-type') or event['headers'].get('Content-Type')
    environ = {'REQUEST_METHOD': 'POST', 'CONTENT_TYPE': content_type}
    fp = BytesIO(event['body'].encode() if isinstance(event['body'], str) else event['body'])
    form = cgi.FieldStorage(fp=fp, environ=environ, keep_blank_values=True)

    to_address_file = form['to_address'] if 'to_address' in form else None
    proxy_file = form['proxy'] if 'proxy' in form else None
    client_key = form.getvalue('client_key')

    if not to_address_file or not proxy_file or not client_key:
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "缺少文件或API密钥"})
        }

    addresses = to_address_file.file.read().decode().splitlines()
    proxies_list = proxy_file.file.read().decode().splitlines()

    if len(addresses) != len(proxies_list):
        return {
            "statusCode": 400,
            "body": json.dumps({"error": "地址和代理数量不一致"})
        }

    website_url = "https://faucet.campnetwork.xyz/"
    website_key = "5b86452e-488a-4f62-bd32-a332445e2f51"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"

    results = []
    for idx, (address, proxy_line) in enumerate(zip(addresses, proxies_list)):
        res = process_one(idx, address, proxy_line, client_key, website_url, website_key, user_agent)
        results.append(res)

    wb = Workbook()
    ws = wb.active
    ws.append(["序号", "地址", "代理", "状态", "返回内容"])
    for row in sorted(results, key=lambda x: x[0]):
        ws.append(row)

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    import base64
    b64_excel = base64.b64encode(output.read()).decode()

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "filename": "result.xlsx",
            "filedata": b64_excel
        }),
    }
