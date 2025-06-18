from flask import Flask, Response, render_template, request, stream_with_context
import httpx, time
from concurrent.futures import ThreadPoolExecutor

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/run")
def run():
    addresses = request.args.get("addresses", "").strip().splitlines()
    proxies = request.args.get("proxies", "").strip().splitlines()
    client_key = request.args.get("client_key", "").strip()

    if not (addresses and proxies and client_key):
        yield f"data: ❌ 参数缺失\n\n"
        return

    if len(addresses) != len(proxies):
        yield f"data: ❌ 地址和代理数量不一致\n\n"
        return

    @stream_with_context
    def event_stream():
        def process_one(i, address, proxy_line):
            try:
                yield f"data: ⏳ 正在处理 {address}...\n\n"
                # 模拟领水过程（你可以用你的真实逻辑）
                time.sleep(1)
                yield f"data: ✅ {i+1}. {address} 领取成功\n\n"
            except Exception as e:
                yield f"data: ❌ {i+1}. {address} 失败: {str(e)}\n\n"

        for i, (addr, proxy) in enumerate(zip(addresses, proxies)):
            yield from process_one(i, addr, proxy)
        yield "data: ✅ 全部完成\n\n"

    return Response(event_stream(), content_type='text/event-stream')
