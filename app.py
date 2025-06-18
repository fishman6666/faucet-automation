from flask import Flask, render_template, request, Response
import time, httpx

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run')
def run():
    addrs = request.args.get('addresses', '').strip().splitlines()
    proxies = request.args.get('proxies', '').strip().splitlines()
    key = request.args.get('client_key', '').strip()
    if not (addrs and proxies and key) or len(addrs)!=len(proxies):
        return "参数错误", 400

    def gen():
        for i, (addr, proxy_line) in enumerate(zip(addrs, proxies)):
            proxy = f"socks5://{proxy_line.split(':')[2]}:{proxy_line.split(':')[3]}@{proxy_line.split(':')[0]}:{proxy_line.split(':')[1]}"
            yield f"data: 🕐 [{i+1}] 代理：{proxy}\n\n"
            # STEP 1: YesCaptcha
            try:
                r = httpx.post(
                    "https://api.yescaptcha.com/createTask",
                    json={"clientKey": key, "task": {
                        "type": "HCaptchaTaskProxyless",
                        "websiteURL":"https://faucet.campnetwork.xyz/",
                        "websiteKey":"5b86452e-488a-4f62-bd32-a332445e2f51",
                        "userAgent":"Mozilla/5.0"
                    }},
                    timeout=60
                )
                j = r.json()
                task_id = j.get("taskId")
                if not task_id:
                    raise Exception("createTask err: " + str(j))
                yield f"data: ✔️ 打码任务创建成功\n\n"
                # STEP 2: 等待结果
                solution = None
                for n in range(20):
                    time.sleep(3)
                    resp = httpx.post(
                        "https://api.yescaptcha.com/getTaskResult",
                        json={"clientKey":key, "taskId":task_id},
                        timeout=60
                    ).json()
                    if resp.get("status")=="ready":
                        solution = resp["solution"]["gRecaptchaResponse"]
                        break
                if not solution:
                    raise Exception("打码超时")
            except Exception as e:
                yield f"data: ❌ 打码失败：{e}\n\n"; continue

            # STEP 3: 领取请求
            try:
                cx = httpx.Client(proxies=proxy, timeout=60)
                resp = cx.post("https://faucet.campnetwork.xyz/api/claim",
                               json={"address":addr},
                               headers={
                                   "h-captcha-response": solution,
                                   "user-agent":"UA",
                               }
                )
                yield f"data: 🧾 {addr} 领取反馈：{resp.status_code} {resp.text}\n\n"
            except Exception as e:
                yield f"data: ❌ 领取失败：{e}\n\n"

            yield "data: -----------------------------\n\n"
            time.sleep(0.1)

        yield "data: ✅ 全部任务完成\n\n"

    return Response(gen(), content_type='text/event-stream')

if __name__ == "__main__":
    app.run(host="0.0.0.0", debug=False)
