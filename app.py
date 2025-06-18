from flask import Flask, render_template, request, Response, stream_with_context
from concurrent.futures import ThreadPoolExecutor
import httpx, time

app = Flask(__name__)

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/run')
def run():
    addrs = request.args.get('addresses','').strip().splitlines()
    proxies = request.args.get('proxies','').strip().splitlines()
    key = request.args.get('client_key','').strip()

    if not (addrs and proxies and key) or len(addrs)!=len(proxies):
        return Response("❌ 参数错误", status=400)

    def event_stream():
        def task(i, addr, proxy_line):
            proxy = f"socks5://{proxy_line.split(':')[2]}:{proxy_line.split(':')[3]}@{proxy_line.split(':')[0]}:{proxy_line.split(':')[1]}"
            yield f"data: 🕐 [{i+1}] 使用代理 {proxy}\n\n"
            time.sleep(1)  # 示例延时
            yield f"data: ✅ [{i+1}] {addr} 完成领取\n\n"

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(task, i, addrs[i], proxies[i]) for i in range(len(addrs))]
            for f in futures:
                for line in f.result():
                    yield line
                time.sleep(0.1)

        yield "data: 🎉 全部完成\n\n"

    return Response(stream_with_context(event_stream()), mimetype='text/event-stream')

if __name__ == "__main__":
    app.run(debug=True)
